"""The governed runner: the provider error's safe cause, the output bound,
the evidence titles of the analysis view, and the ``runner: seat`` refusal."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from app.services.model_gateway.litellm import LiteLLMGatewayError
from app.services.model_gateway.litellm.errors import GATEWAY_STATE_REQUEST_REJECTED
from app.services.model_gateway.litellm.upstream_detail import upstream_error_detail
from app.services.work_item_analysis.auto_start import auto_candidates
from app.services.work_item_analysis.runner import analyze_work_item
from tests.agent_gateway.seat_presence_support import _bearer
from tests.work_item_analysis.support import (
    MANUAL_PAGE,
    POLICY,
    Scripted,
    analysis,
    final,
    gateway_runtimes,
    run_options,
    seed_env,
    tool_call,
)
from tests.work_item_analysis.test_settings_and_routes import ITEMS, _operator

KEY = ("sk-li" + "ve-0123456789abcdefABCDEF0123456789")
UPSTREAM = f"BedrockException - `temperature` is deprecated for this model. api_key={KEY} Bearer {KEY}"


class Failing:
    def __init__(self, body: bytes, *, safe_detail: str | None = None) -> None:
        self.body = body
        self.safe_detail = safe_detail

    def __call__(self, **_kwargs: Any) -> Any:
        failing = self

        class _Provider:
            async def chat(self, messages, model=None, tools=None, **_ignored):
                error = LiteLLMGatewayError(GATEWAY_STATE_REQUEST_REJECTED, status_code=400,
                                            upstream_detail=upstream_error_detail(failing.body))
                if failing.safe_detail is not None:  # a provider that put raw text into its detail
                    error.safe_detail = failing.safe_detail
                raise error

            async def close(self):
                return None

        return _Provider()


class Bounded(Scripted):
    def __call__(self, **_kwargs: Any) -> Any:
        scripted = self

        class _Provider:
            async def chat(self, messages, model=None, tools=None, max_tokens=None, **_ignored):
                scripted.seen.append({"max_tokens": max_tokens, "model": model})
                return {**scripted.script.pop(0), "model": model or ""}

            async def close(self):
                return None

        return _Provider()


@pytest.mark.asyncio
async def test_a_provider_error_keeps_its_safe_cause_on_the_row_the_view_and_the_log(db, monkeypatch, caplog):
    env = await seed_env(db, monkeypatch)
    body = json.dumps({"error": {"code": "bad_request", "message": UPSTREAM}}).encode()
    with caplog.at_level(logging.WARNING):
        result = await analyze_work_item(db, item=env.item, user=env.user, get_provider=Failing(body),
                                         resolve_runtimes=gateway_runtimes)
    assert (result["status"], result["error_code"]) == ("failed", "provider_error")
    detail = result["error_detail"]
    assert detail.startswith("analysis-alias: permanent: request_rejected (HTTP 400): BedrockException")
    assert "`temperature` is deprecated for this model" in detail
    assert KEY not in detail and "0123456789abcdef" not in detail and len(detail) <= 300
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "work_item_analysis_failed" in logged and "temperature" in logged and KEY not in logged


@pytest.mark.asyncio
async def test_a_raw_provider_detail_is_sanitized_again_before_it_is_stored(db, monkeypatch):
    env = await seed_env(db, monkeypatch)
    raw = f"upstream said: token={KEY} and Authorization: Bearer {KEY}"
    result = await analyze_work_item(db, item=env.item, user=env.user, resolve_runtimes=gateway_runtimes,
                                     get_provider=Failing(b"", safe_detail=raw))
    assert result["error_code"] == "provider_error"
    assert "upstream said" in result["error_detail"] and KEY not in result["error_detail"]


@pytest.mark.asyncio
async def test_each_request_uses_the_workspace_output_bound(db, monkeypatch):
    env = await seed_env(db, monkeypatch)
    search = tool_call("knowledge_search", {"query": "TLS"})
    default = Bounded([search, final(analysis())])
    assert (await analyze_work_item(db, item=env.item, user=env.user, **run_options(default)))["status"] == "succeeded"
    assert [seen["max_tokens"] for seen in default.seen] == [8192, 8192]

    other = await seed_env(db, monkeypatch, settings={"model_policy": f"{POLICY}@1", "max_output_tokens": 16000})
    bounded = Bounded([search, final(analysis())])
    done = await analyze_work_item(db, item=other.item, user=other.user, **run_options(bounded))
    assert [seen["max_tokens"] for seen in bounded.seen] == [16000, 16000]
    assert done["model"] == "analysis-alias" and done["runner"] == "governed"


@pytest.mark.asyncio
async def test_the_latest_analysis_names_each_evidence_title(client, db, monkeypatch):
    env = await seed_env(db, monkeypatch)
    await _operator(db, env.user.id)
    search = tool_call("knowledge_search", {"query": "TLS"})
    await analyze_work_item(db, item=env.item, user=env.user, **run_options(Scripted([search, final(analysis())])))
    latest = (await client.get(f"{ITEMS}/{env.item.id}/analysis", headers=await _bearer(env.user.id))).json()
    entry = latest["analysis"]["evidence"][0]
    assert (entry["title"], entry["locator"], entry["kind"], entry["verified"]) == (
        "Vendor manual", MANUAL_PAGE, "manual", True)
    assert entry["source"]["title"] == "Vendor manual"  # the stored contract shape is kept
    assert latest["error_detail"] is None


@pytest.mark.asyncio
async def test_a_seat_runner_workspace_never_runs_a_model_and_names_the_command(db, monkeypatch):
    env = await seed_env(db, monkeypatch, settings={"model_policy": f"{POLICY}@1", "runner": "seat",
                                                    "auto_analyze": {"jira_label": "octryx"}})
    scripted = Scripted([final(analysis())])
    result = await analyze_work_item(db, item=env.item, user=env.user, **run_options(scripted))
    assert (result["status"], result["error_code"], result["runner"]) == ("skipped", "analysis_runs_in_seat", "seat")
    assert result["command"] == f"octryx-claude analyze {env.item.source_key}"
    assert scripted.seen == []
    assert await auto_candidates(db, project_id=env.workspace_id, source_type="jira") == []
