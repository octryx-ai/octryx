"""The platform redacts transcripts itself, on storing and on reading, never relying on the launcher."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.models import Session, SessionTranscriptChunk
from app.services.agent_gateway.contract import SESSION_KEY_METADATA
from app.services.artifact_store import service as artifact_service
from app.services.session_transcripts.redaction import redact_entry
from app.services.session_transcripts.store import encode_lines, object_location
from tests.session_transcripts.test_session_transcripts import (
    BATCH,
    READ,
    _bearer,
    _setup,
    _switch_on,
)
from tests.session_transcripts.transcript_store_support import artifact_dir  # noqa: F401 - autouse fixture

STRIPE = ("sk_live_" + "51HxQabcdefghijklmnopqrstu")
DB_PASSWORD = "app-db-pw-9f8e7d"
SECRET_PASSWORD = "hunter2-raw-value"
SECRET_STRING = json.dumps({"username": "app", "password": SECRET_PASSWORD})
ENV_FILE = f"STRIPE_KEY={STRIPE}\nDATABASE_URL=postgres://app:{DB_PASSWORD}@db:5432/app\nDEBUG=true\n"


def _env_read_result() -> dict:
    return {"type": "user", "toolUseResult": {"type": "text", "file": {"filePath": "/repo/.env", "content": ENV_FILE}},
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "r1",
                                                       "content": ENV_FILE}]}}


def _secrets_call() -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "b1", "name": "Bash", "input": {
        "command": "aws secretsmanager get-secret-value --secret-id prod/db"}}]}}


def _secrets_output() -> dict:
    output = json.dumps({"ARN": "arn:aws:secretsmanager:eu-central-1:1:secret:prod/db", "Name": "prod/db",
                         "SecretString": SECRET_STRING})
    return {"type": "user", "toolUseResult": {"stdout": output, "stderr": ""},
            "message": {"content": [{"type": "tool_result", "tool_use_id": "b1", "content": output}]}}


def _text(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


# One case per rule: (text, the secret that must go, what must stay)
PATTERNS = [
    ("STRIPE_KEY=abc123plain", "abc123plain", "STRIPE_KEY="),
    ("db_password: s3cr3tvalue", "s3cr3tvalue", "db_password:"),
    ("export GITHUB_AUTH='tok-plain-1'", "tok-plain-1", "GITHUB_AUTH="),
    ("AZURE_CONNECTION_STRING=Endpoint=sb://x;SharedAccessKey=zzz", "zzz", "AZURE_CONNECTION_STRING"),
    ("MY_PRIVATE=thing-42", "thing-42", "MY_PRIVATE="),
    (f"key is {STRIPE}", STRIPE, "key is"),
    (("rk_live_" + "51Habcdefghijklmnop"), ("rk_live_" + "51Habcdefghijklmnop"), ""),
    ("ghp_" + "a1B2c3D4e5" * 4, "a1B2c3D4e5a1B2c3D4e5", ""),
    ("github_pat_11ABCDEFG0123456789_abcdefghij", "11ABCDEFG0123456789_abcdefghij", ""),
    ("slack xoxb-1234567890-abcdefghij", "xoxb-1234567890-abcdefghij", "slack"),
    (("id AKIAAB" + "CDEFGHIJKLMNOP"), ("AKIAAB" + "CDEFGHIJKLMNOP"), "id"),
    ("aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "wJalrXUtnFEMI", ""),
    (("gitlab glpat-ab" + "cdefghijklmnopqrst"), ("glpat-ab" + "cdefghijklmnopqrst"), "gitlab"),
    (("jwt eyJhb" + "GciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"),
     "dozjgNryP4J3jVmNHl0w5N", "jwt"),
    ("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----", "MIIEowIBAAKCAQEA", ""),
    (("curl -H 'Authorization: Bearer abcd" + "efghijklmnop1234'"), ("abcd" + "efghijklmnop1234"), "curl"),
    ("postgres://app:pw-in-url@db/app", "pw-in-url", "postgres://"),
    ('{"password": "pw-json-1", "user": "x"}', "pw-json-1", '"user": "x"'),
    ('{"client_secret": "cs-json-2"}', "cs-json-2", "client_secret"),
    (json.dumps({"outer": json.dumps({"api_key": "ak-escaped-3"})}), "ak-escaped-3", "outer"),
    (json.dumps({"SecretString": json.dumps({"token": "nested-4"})}), "nested-4", "SecretString"),
    ('{"a": {"b": {"private_key": "pk-deep-5"}}}', "pk-deep-5", '"a"'),
    ('{"access_key": "acc-6"}', "acc-6", "access_key"),
]


@pytest.mark.parametrize(("text", "secret", "kept"), PATTERNS)
def test_every_rule_redacts_its_secret(text, secret, kept):
    redacted = redact_entry(_text(text))["message"]["content"][0]["text"]
    assert secret not in redacted and kept in redacted


@pytest.mark.parametrize("path", ["/r/.env", "/r/.env.production", "/r/certs/tls.pem", "/home/u/.ssh/id_ed25519",
                                  "/home/u/.npmrc", "/home/u/.netrc", "/home/u/.aws/credentials", "/r/server.key"])
def test_a_credential_file_read_is_replaced_whole(path):
    line = {"type": "user", "toolUseResult": {"file": {"filePath": path, "content": "harmless-looking-value"}},
            "message": {"content": [{"type": "tool_result", "tool_use_id": "x", "content": "harmless-looking-value"}]}}
    assert "harmless-looking-value" not in json.dumps(redact_entry(line))
    ordinary = json.loads(json.dumps(line).replace(path, "/r/app/id_utils.py"))
    assert "harmless-looking-value" in json.dumps(redact_entry(ordinary))


async def _stored(artifact_root) -> str:
    import gzip

    return "".join(gzip.decompress(path.read_bytes()).decode() for path in artifact_root.rglob("*.jsonl.gz"))


@pytest.mark.asyncio
async def test_both_incidents_are_redacted_on_storing_without_the_launcher(client, db, artifact_dir):  # noqa: F811
    workspace, _owner, admin, _other, headers = await _setup(client, db)
    await _switch_on(client, workspace, admin)
    session = headers["x-octryx-session"]

    async def send(first_line, lines):
        body = {"claude_session_id": session, "stream": "main", "first_line": first_line, "lines": lines}
        answer = await client.post(BATCH, json=body, headers=headers)
        assert answer.json()["state"] == "stored", answer.text

    # Unredacted lines as a launcher without its own pass (or any other caller) would send them. The secret
    # command's call and its output arrive in different batches.
    await send(1, [_env_read_result(), _text(f"I found STRIPE_KEY={STRIPE} in the env"), _secrets_call()])
    await send(4, [_secrets_output()])
    stored = await _stored(artifact_dir)
    for secret in (STRIPE, DB_PASSWORD, SECRET_PASSWORD, "hunter2"):
        assert secret not in stored
    assert "[redacted: output of a secret command or credential file]" in stored


@pytest.mark.asyncio
async def test_both_incidents_are_redacted_on_reading_whatever_the_store_holds(client, db, artifact_dir):  # noqa: F811
    workspace, owner, admin, _other, headers = await _setup(client, db)
    await _switch_on(client, workspace, admin)
    session = (await db.execute(select(Session).where(
        Session.metadata_[SESSION_KEY_METADATA].as_string() == headers["x-octryx-session"]))).scalar_one()
    # A raw object in the store (written by anything): the read must still redact it with the rules in force.
    raw = [[_env_read_result(), _secrets_call()], [_secrets_output(), _text(f"STRIPE_KEY={STRIPE}")]]
    for index, lines in enumerate(raw):
        first = 1 + 2 * index
        location = object_location("filesystem", project_id=workspace, session_id=session.id, stream="main",
                                   first_line=first)
        artifact_service._write_artifact_object(backend="filesystem", location=location,
                                                payload_bytes=encode_lines(lines))
        db.add(SessionTranscriptChunk(project_id=workspace, session_id=session.id, owner_user_id=owner,
                                      claude_session_id="raw-session", stream="main", first_line=first,
                                      last_line=first + 1, line_count=2, byte_size=1, storage_backend="filesystem",
                                      storage_location=location))
    await db.commit()

    full = (await client.get(READ.format(session.id), headers=await _bearer(owner))).json()
    page_two = (await client.get(READ.format(session.id), params={"from_line": 3},
                                 headers=await _bearer(admin))).json()  # the call is on the page before
    for page in (full, page_two):
        served = json.dumps(page)
        for secret in (STRIPE, DB_PASSWORD, SECRET_PASSWORD):
            assert secret not in served
    assert page_two["lines"][0]["entry"]["toolUseResult"] == "[redacted: output of a secret command or credential file]"
