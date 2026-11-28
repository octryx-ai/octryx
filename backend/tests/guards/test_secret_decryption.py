from __future__ import annotations

import ast

from tests.guards._support import APP, BACKEND, Accepted, assert_guard

PRIMITIVES = frozenset({"decrypt_secret", "decrypt_bytes", "_fernet"})
CHOKE_POINT = "app/services/secret/access.py"

ALLOWED_DECRYPTION = (
    Accepted(f"{CHOKE_POINT}::decrypt_secret", "the choke point: records the use, then decrypts"),
    Accepted("app/services/agent_gateway/hook_key.py::decrypt_secret",
             "the launcher's own per-session proof key, checked in place; never leaves the proof check"),
    Accepted("app/services/secret_masking.py::decrypt_secret",
             "a write plan's own sealed field values (what the model wrote), not a stored credential"),
    Accepted("app/services/devices/engine_state.py::decrypt_bytes",
             "a session's engine files, handed only to the device that holds the session's active job"),
)


def decryption_sites(sources: dict[str, str]) -> set[str]:
    sites = set()
    for path, source in sources.items():
        if path == "app/services/secret/crypto.py":
            continue
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom):
                names = {alias.name for alias in node.names}
            elif isinstance(node, ast.Name | ast.Attribute):
                names = {node.id if isinstance(node, ast.Name) else node.attr}
            else:
                continue
            sites.update(f"{path}::{name}" for name in names & PRIMITIVES)
    return sites


def _app_sources() -> dict[str, str]:
    return {str(path.relative_to(BACKEND)): path.read_text(encoding="utf-8") for path in sorted(APP.rglob("*.py"))}


def test_secrets_are_decrypted_only_at_the_choke_point() -> None:
    assert_guard(decryption_sites(_app_sources()), ALLOWED_DECRYPTION, what="secret decryption")


_PLANTED = '''
from app.services.secret.crypto import decrypt_secret


async def leak(row):
    return decrypt_secret(row.encrypted_value)
'''


def test_the_guard_catches_a_new_direct_decrypt_call() -> None:
    planted = "app/services/planted_reader.py"
    assert decryption_sites({planted: _PLANTED}) == {f"{planted}::decrypt_secret"}

