"""Teams call privacy: recordings are spooled owner-only and removed; logs name no caller."""

from __future__ import annotations

import logging
import stat

import pytest

from app.config import get_settings
from app.services.person_log_ref import NO_PERSON, person_log_ref
from app.services.speaker import voice_enrollment
from app.services.teams_calling import recording_processor, recording_spool

CALLER = "Jane Example-Caller"
AUDIO = b"RIFF" + b"\x00" * 64


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_the_spool_is_owner_only_and_removed_afterwards(tmp_path):
    directory = tmp_path / "recordings"

    with recording_spool.spooled_recording(AUDIO, directory=directory) as path:
        assert path is not None and path.parent == directory
        assert path.read_bytes() == AUDIO
        assert _mode(directory) == 0o700
        assert _mode(path) == 0o600
        assert "call" not in path.name

    assert not path.exists()
    assert list(directory.iterdir()) == []


def test_the_spool_is_removed_when_processing_fails(tmp_path):
    directory = tmp_path / "recordings"

    with pytest.raises(RuntimeError), recording_spool.spooled_recording(AUDIO, directory=directory) as path:
        raise RuntimeError("turn failed")

    assert path is not None and not path.exists()


def test_a_spool_failure_does_not_stop_the_turn_and_logs_a_code(tmp_path, caplog):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger=recording_spool.__name__):
        with recording_spool.spooled_recording(AUDIO, directory=blocker / "recordings") as path:
            assert path is None

    assert "call_recording_spool_failed error_type=" in caplog.text
    assert str(tmp_path) not in caplog.text


def test_recordings_live_in_the_configured_data_directory():
    from pathlib import Path

    data_dir = Path(get_settings().artifact_store_dir).expanduser().resolve().parent
    assert recording_spool.recordings_dir() == data_dir / recording_spool.RECORDINGS_DIRNAME


@pytest.mark.asyncio
async def test_processing_spools_during_the_turn_and_logs_no_caller_name(monkeypatch, tmp_path, capsys, caplog):
    directory = tmp_path / "recordings"
    monkeypatch.setattr(recording_spool, "recordings_dir", lambda: directory)

    class _Response:
        content = AUDIO

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, *args, **kwargs):
            return _Response()

    seen: list[list[str]] = []

    async def fake_turn(item, audio_bytes, db):
        seen.append([path.name for path in directory.iterdir()])

    monkeypatch.setattr(recording_processor.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(recording_processor, "_process_downloaded_recording", fake_turn)
    item = {
        "call_id": "call-1",
        "channel_id": "channel-1",
        "recording_location": "https://graph.example/recording",
        "recording_access_token": "token",
        "caller_display_name": CALLER,
        "is_direct_call": True,
    }

    with caplog.at_level(logging.DEBUG):
        await recording_processor._process_one_recording(item, db=None)

    assert len(seen) == 1 and len(seen[0]) == 1 and seen[0][0].endswith(".wav")
    assert list(directory.iterdir()) == []
    output = capsys.readouterr().err + caplog.text
    assert CALLER not in output
    assert person_log_ref(CALLER) in output


def test_enrollment_logs_an_opaque_reference(caplog):
    with caplog.at_level(logging.INFO, logger=voice_enrollment.__name__):
        voice_enrollment.start_enrollment("call-2", CALLER, "project-1")
        voice_enrollment.detect_enrollment_command("please save my voice", caller_display_name=CALLER)
    voice_enrollment._enrollment_sessions.pop("call-2", None)

    assert CALLER not in caplog.text
    assert "please save" not in caplog.text
    assert person_log_ref(CALLER) in caplog.text


def test_person_log_ref_is_stable_opaque_and_empty_safe():
    ref = person_log_ref(CALLER)
    assert ref == person_log_ref(f"  {CALLER} ")
    assert ref.startswith("person-") and len(ref) == len("person-") + 12
    assert "jane" not in ref.lower()
    assert ref != person_log_ref("Another Caller")
    assert person_log_ref("") == person_log_ref(None) == NO_PERSON
