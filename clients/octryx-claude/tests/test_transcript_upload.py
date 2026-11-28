from __future__ import annotations

import json
from pathlib import Path

import httpx

from octryx_claude import transcript_streams, transcript_upload
from octryx_claude.platform import SessionContext
from octryx_claude.transcript_redact import SECRET_OUTPUT

from .conftest import BASE_URL

SESSION = "7cdbc6d0-b028-4677-964e-e3e99ea9b98f"
CONTEXT = SessionContext(BASE_URL, SESSION, "ws-1")


class Platform:
    def __init__(self, *answers: tuple[int, dict]) -> None:
        self.answers = list(answers)
        self.batches: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/agent-gateway/sessions/transcript"
        status, body = self.answers.pop(0) if self.answers else (200, {"state": "stored"})
        if status == 200 and body.get("state") == "stored":
            self.batches.append(json.loads(request.content))
        return httpx.Response(status, json=body)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def _write(path: Path, entries: list, *, tail: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("".join(json.dumps(entry) + "\n" for entry in entries) + tail)


def _text(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def _files(config_dir: Path) -> tuple[Path, Path]:
    folder = config_dir / "projects" / "-Users-dev-repo"
    return folder / f"{SESSION}.jsonl", folder / SESSION / "subagents" / "agent-a1b2c3.jsonl"


def _shipper(state, config_dir: Path) -> transcript_upload.Shipper:
    return transcript_upload.Shipper(state, CONTEXT, config_dir, SESSION, "dj_0011aabb").load()


def test_off_starts_nothing_and_sends_nothing(state, tmp_path):
    def no_client():
        raise AssertionError("no HTTP client while the switch is off")

    assert transcript_upload.enabled({}) is False
    assert transcript_upload.enabled({"session_transcripts": {"enabled": False}}) is False
    assert transcript_upload.enabled({"session_transcripts": {"enabled": True}}) is True
    main, _sub = _files(tmp_path / "config")
    _write(main, [_text("hello")])
    with transcript_upload.running(state, CONTEXT, config_dir=tmp_path / "config", claude_session_id=SESSION,
                                   on=False, client_factory=no_client) as upload:
        assert upload is None
    assert not (state.root / transcript_upload.OUTBOX_DIR).exists()


def test_on_sends_main_and_subagents_once_and_continues_after_a_restart(state, tmp_path):
    config = tmp_path / "config"
    main, sub = _files(config)
    _write(main, [_text("one"), _text("two")])
    _write(sub, [_text("subagent")])
    platform = Platform()
    with platform.client() as http:
        assert _shipper(state, config).ship_round(http) is True
    sent = {(batch["stream"], batch["first_line"]): batch for batch in platform.batches}
    assert set(sent) == {("main", 1), ("agent-a1b2c3", 1)}
    assert [line["message"]["content"][0]["text"] for line in sent[("main", 1)]["lines"]] == ["one", "two"]
    assert sent[("main", 1)]["claude_session_id"] == SESSION and sent[("main", 1)]["device_job_id"] == "dj_0011aabb"

    _write(main, [_text("three")], tail='{"type": "assistant", "half')  # the last line is still being written
    platform.batches.clear()
    with platform.client() as http:
        assert _shipper(state, config).ship_round(http) is True  # a new launcher process: offsets from disk
    assert [(batch["stream"], batch["first_line"], len(batch["lines"])) for batch in platform.batches] == [
        ("main", 3, 1)]


def test_an_unreachable_platform_loses_nothing(state, tmp_path):
    config = tmp_path / "config"
    main, _sub = _files(config)
    _write(main, [_text("one")])
    platform = Platform((503, {}))
    shipper = _shipper(state, config)
    with platform.client() as http:
        assert shipper.ship_round(http) is False
        assert platform.batches == []
        assert shipper.ship_round(http) is True
    assert [(batch["first_line"], len(batch["lines"])) for batch in platform.batches] == [(1, 1)]


def test_the_platform_saying_off_stops_at_once_and_forgets(state, tmp_path):
    config = tmp_path / "config"
    main, _sub = _files(config)
    _write(main, [_text("one")])
    platform = Platform()
    shipper = _shipper(state, config)
    with platform.client() as http:
        shipper.ship_round(http)
        assert shipper.path.exists()
        _write(main, [_text("after the switch")])
        platform.answers.append((200, {"state": "off"}))
        assert shipper.ship_round(http) is False
        _write(main, [_text("never sent")])
        assert shipper.ship_round(http) is False
    assert shipper.stopped and not shipper.path.exists()
    assert [batch["first_line"] for batch in platform.batches] == [1]


def test_secrets_stay_on_the_mac_and_file_contents_go(state, tmp_path):
    config = tmp_path / "config"
    main, _sub = _files(config)
    raw_secret = "s3cr3t-raw-value-without-any-shape"
    _write(main, [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Bash",
             "input": {"command": "aws secretsmanager get-secret-value --secret-id db"}},
            {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/repo/.env"}},
            {"type": "tool_use", "id": "t3", "name": "Read", "input": {"file_path": "/repo/app.py"}}]}},
        {"type": "user", "toolUseResult": {"stdout": raw_secret},
         "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": raw_secret}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2",
                                                   "content": "DB_PASSWORD_PLAIN_VALUE"}]}},
        {"type": "user", "toolUseResult": {"file": {"content": "def total(items):\n    return sum(items)\n"}},
         "message": {"content": [{"type": "tool_result", "tool_use_id": "t3", "content": "return sum(items)"}]}},
        _text(("my key is AKIAAB" + "CDEFGHIJKLMNOP and token=ghp_") + "a1B2c3D4e5" * 4),
    ])
    platform = Platform()
    with platform.client() as http:
        _shipper(state, config).ship_round(http)
    sent = json.dumps(platform.batches)
    for secret in (raw_secret, "DB_PASSWORD_PLAIN_VALUE", ("AKIAAB" + "CDEFGHIJKLMNOP"), "a1B2c3D4e5a1B2c3D4e5"):
        assert secret not in sent
    lines = platform.batches[0]["lines"]
    assert lines[1]["toolUseResult"] == SECRET_OUTPUT and lines[2]["message"]["content"][0]["content"] == SECRET_OUTPUT
    assert lines[3]["toolUseResult"]["file"]["content"] == "def total(items):\n    return sum(items)\n"


def test_the_session_end_sends_what_is_left_and_clears_the_outbox(state, tmp_path):
    config = tmp_path / "config"
    main, sub = _files(config)
    platform = Platform()
    with transcript_upload.running(state, CONTEXT, config_dir=config, claude_session_id=SESSION, on=True,
                                   interval=3600, client_factory=platform.client) as upload:
        assert upload is not None
        _write(main, [_text("written during the session")])
        _write(sub, [_text("a subagent's step")])
    assert {batch["stream"] for batch in platform.batches} == {"main", "agent-a1b2c3"}
    assert not upload.shipper.path.exists()


def test_the_transcript_id_of_a_terminal_session():
    key = "11111111-2222-3333-4444-555555555555"
    assert transcript_streams.claude_session_for(key, []) == key
    assert transcript_streams.claude_session_for(key, ["--resume", SESSION]) == SESSION
    assert transcript_streams.claude_session_for(key, [f"--resume={SESSION}"]) == SESSION
    assert transcript_streams.claude_session_for(key, ["--continue"]) == ""
    assert transcript_streams.claude_session_for(key, ["-r", SESSION, "--fork-session"]) == ""


def test_a_device_turn_uploads_only_when_its_session_found_the_switch_on(state, tmp_path):
    class Prepared:
        session_key = "11111111-2222-3333-4444-555555555555"
        extra: dict = {}

    assert transcript_upload.start_for_turn(Prepared(), {"job_id": "dj_1"}) is None
    Prepared.extra = {transcript_upload.EXTRA_KEY: {"state": state, "context": CONTEXT,
                                                    "config_dir": str(tmp_path / "config")}}
    fresh = transcript_upload.start_for_turn(Prepared(), {"job_id": "dj_1", "resume": None})
    resumed = transcript_upload.start_for_turn(Prepared(), {"job_id": "dj_1", "resume": SESSION})
    forked = transcript_upload.start_for_turn(Prepared(), {"job_id": "dj_1", "resume": SESSION, "fork": True})
    try:
        assert fresh.shipper.claude_session_id == Prepared.session_key
        assert resumed.shipper.claude_session_id == SESSION and resumed.shipper.job_id == "dj_1"
        assert forked.shipper.claude_session_id == Prepared.session_key
        forked.bind("99999999-8888-7777-6666-555555555555")  # the id Claude Code reported for the fork
        assert forked.shipper.claude_session_id == "99999999-8888-7777-6666-555555555555"
    finally:
        for upload in (fresh, resumed, forked):
            upload.stop(wait=0)
