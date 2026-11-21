"""Every turn reports the tokens it used, read from its transcripts, so the platform can price it: a turn without
``claude -p``'s result (follow-up) and one with it, whose ``total_cost_usd`` is the session's running total
."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from octryx_claude.transcript_usage import transcripts, turn_usage
from tests.device_jobs_support import FakeDriver, _manager, _offer, _settle

SESSION = "00000000-0000-4000-8000-000000000001"


def _line(minutes, message_id, model, **usage):
    when = (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")
    return json.dumps({"type": "assistant", "timestamp": when,
                       "message": {"id": message_id, "model": model, "usage": usage}}) + "\n"


def _session(config_dir):
    folder = config_dir / "projects" / "-repo"
    (folder / SESSION / "subagents").mkdir(parents=True)
    (folder / f"{SESSION}.jsonl").write_text(
        _line(-60, "m0", "claude-sonnet-5-5", input_tokens=999)  # an earlier turn: not this one's
        + _line(1, "m1", "claude-sonnet-5-5", input_tokens=10, output_tokens=5, cache_read_input_tokens=100,
                cache_creation_input_tokens=50, cache_creation={"ephemeral_1h_input_tokens": 30})
        + _line(1, "m1", "claude-sonnet-5-5", input_tokens=10, output_tokens=5, cache_read_input_tokens=100,
                cache_creation_input_tokens=50, cache_creation={"ephemeral_1h_input_tokens": 30})
        + _line(2, "m2", "<synthetic>", input_tokens=0, output_tokens=0))
    (folder / SESSION / "subagents" / "agent-a1.jsonl").write_text(
        _line(1, "s1", "claude-haiku-5-5", input_tokens=3, output_tokens=7, cache_creation_input_tokens=40))


def test_each_message_counts_once_per_model_subagents_included(tmp_path):
    _session(tmp_path)
    started = datetime.now(UTC).timestamp()
    usage = turn_usage(transcripts(tmp_path, SESSION), started)
    assert usage["by_model"] == {
        "claude-sonnet-5-5": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100,
                              "cache_creation_input_tokens": 50, "cache_creation_1h_input_tokens": 30},
        "claude-haiku-5-5": {"input_tokens": 3, "output_tokens": 7, "cache_read_input_tokens": 0,
                             "cache_creation_input_tokens": 40, "cache_creation_1h_input_tokens": 0}}
    assert (usage["input_tokens"], usage["output_tokens"], usage["source"]) == (13, 12, "transcript")
    assert turn_usage(transcripts(tmp_path, "other-session"), started) is None


class NoResultDriver(FakeDriver):
    async def run_turn(self, prepared, **kwargs):
        await super().run_turn(prepared, **kwargs)
        return {"status": "success", "result_text": "Done.", "claude_session_id": SESSION}  # no result JSON


@pytest.mark.asyncio
async def test_a_turn_without_a_result_reports_its_transcript_usage(state, tmp_path, monkeypatch):
    _session(tmp_path / "claude")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    manager, channel, repo = _manager(state, tmp_path, driver=NoResultDriver())
    await manager.handle("job_offer", _offer(repo))
    await _settle(manager)
    finished = channel.of("turn_finished")[0]
    assert "cost_usd" not in finished  # the platform prices it from its catalog
    assert finished["usage"]["source"] == "transcript" and finished["usage"]["output_tokens"] == 12


class ResultDriver(FakeDriver):
    async def run_turn(self, prepared, **kwargs):
        await super().run_turn(prepared, **kwargs)
        return {"status": "success", "result_text": "Done.", "claude_session_id": SESSION, "cost_usd": 187.19,
                "usage": {"input_tokens": 1}}  # the session's running total, not this turn's cost


@pytest.mark.asyncio
async def test_a_turn_with_claude_codes_result_reports_its_transcript_usage_too(state, tmp_path, monkeypatch):
    _session(tmp_path / "claude")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    manager, channel, repo = _manager(state, tmp_path, driver=ResultDriver())
    await manager.handle("job_offer", _offer(repo))
    await _settle(manager)
    finished = channel.of("turn_finished")[0]
    assert finished["cost_usd"] == 187.19  # Claude Code's running total, passed on as information only
    assert finished["usage"]["source"] == "transcript" and finished["usage"]["by_model"]["claude-sonnet-5-5"][
        "cache_creation_1h_input_tokens"] == 30


@pytest.mark.asyncio
async def test_a_turn_without_a_transcript_keeps_the_drivers_usage(state, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))  # nothing written there (pi, Codex)
    manager, channel, repo = _manager(state, tmp_path)
    await manager.handle("job_offer", _offer(repo))
    await _settle(manager)
    assert "usage" not in channel.of("turn_finished")[0]
