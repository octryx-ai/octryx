"""At the runtime boundary web answers are marked or recorded, and web search and fetch results carry their source URL."""

from __future__ import annotations

import ipaddress
from types import SimpleNamespace

import httpx
import pytest

from app.services.answer_evidence.evidence import collect_turn_evidence
from app.services.web_search.providers import SearchHit
from app.services.web_search.service import SearchOutcome
from app.tools.runtime_impl._runtime_web_search_tools import _answer
from tests.answer_evidence_guard_support import PETCLINIC_OWNER
from tests.egress_support import answer_public_web

# --- end to end over run_agent ---------------------------------------------------------------------




















# --- web evidence carries its URL -------------------------------------------------------------------


def test_web_search_results_carry_source_url_and_cite_as() -> None:
    outcome = SearchOutcome(state="ok", reason="ok", provider="tavily", hits=[SearchHit("Owner.java", PETCLINIC_OWNER, "x")])
    hit = _answer(outcome, query="petclinic owner", mode="open")["results"][0]
    assert (hit["source_title"], hit["source_url"], hit["cite_as"]) == (
        "Owner.java",
        PETCLINIC_OWNER,
        f"[Owner.java]({PETCLINIC_OWNER})",
    )
    assert collect_turn_evidence([{"tool_name": "web_search", "result": {"results": [hit]}}]).evidence_bearing


@pytest.mark.asyncio
async def test_web_fetch_results_carry_source_url_and_the_page_title(monkeypatch) -> None:
    from app.tools.runtime_impl._runtime_bash_web import WebFetchTool

    async def resolve(hostname: str, port: int | None):
        return {ipaddress.ip_address("93.184.216.34")}

    def handler(request):
        page = "<html><head><title>Owner &amp; Pets</title></head><body>x</body></html>"
        return httpx.Response(200, headers={"content-type": "text/html"}, text=page, request=request)

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", resolve)
    answer_public_web(monkeypatch, handler)

    result = await WebFetchTool().execute({"url": "https://example.com/owner"}, SimpleNamespace())

    assert result["source_url"] == "https://example.com/owner"
    assert result["cite_as"] == "[Owner & Pets](https://example.com/owner)"
