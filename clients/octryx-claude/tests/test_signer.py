"""Hook signer: signs only this session's confirmation messages, over a private socket."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import stat

from octryx_claude import signer

KEY = ("0b6c" + "4a52-3b1e-4c1b-9f55-1d1c1b1a1f10")
OTHER = "9f3e1d2c-0000-4000-8000-000000000001"
HOOK_KEY = b"k" * 32
NONCE = "0123456789abcdef0123456789abcdef"


def _raw(path, payload: bytes) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(3)
        conn.connect(str(path))
        conn.sendall(payload)
        return json.loads(conn.makefile("rb").readline())


def test_signs_only_well_formed_messages_of_its_own_session(short_state):
    message = signer.confirm_message(KEY, "toolu_01AbC-d", "3f2a-77", NONCE, 1790000000)
    with signer.start_signer(short_state, KEY, HOOK_KEY) as running:
        assert stat.S_IMODE(os.stat(running.path).st_mode) == 0o600
        mac = signer.sign(short_state, KEY, message)
        assert mac == hmac.new(HOOK_KEY, message.encode(), hashlib.sha256).hexdigest()

        for refused in (
            signer.confirm_message(OTHER, "toolu_01", "3f2a-77", NONCE, 1790000000),
            signer.confirm_message(KEY, "toolu 01", "3f2a-77", NONCE, 1790000000),
            signer.confirm_message(KEY, "toolu_01", "3f2a_77", NONCE, 1790000000),
            signer.confirm_message(KEY, "toolu_01", "3f2a-77", NONCE.upper(), 1790000000),
            signer.confirm_message(KEY, "toolu_01", "3f2a-77", NONCE, 179000000),
            message + "\n",
            message.replace("v1|confirm", "v1|deny"),
        ):
            assert signer.sign(short_state, KEY, refused) is None
            assert _raw(running.path, (json.dumps({"op": "sign", "message": refused}) + "\n").encode()) == {
                "error": "message_refused"}
        assert _raw(running.path, b"x" * (signer.MAX_REQUEST_BYTES + 10) + b"\n") == {"error": "request_too_large"}
        assert _raw(running.path, b'{"op": "verify"}\n') == {"error": "invalid_request"}
        # The signer survives bad requests.
        assert signer.sign(short_state, KEY, message) == mac
    assert not running.path.exists()
    assert signer.sign(short_state, KEY, message) is None
