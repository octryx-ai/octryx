"""Content security — the coverage from what is configured, the shipped platform content
policies enforced on every model call."""

from __future__ import annotations

import pytest

from tests.policy_engine_support import bearer, make_user

ROUTE = "/api/v1/admin/content-security"


def _cell(body: dict, surface: str, category: str) -> dict:
    row = next(item for item in body["coverage"]["rows"] if item["key"] == surface)
    return next(cell for cell in row["cells"] if cell["category"] == category)


@pytest.mark.asyncio
async def test_the_coverage_shows_what_is_configured_and_gaps_as_gaps(client, db):
    admin = await make_user(db, admin=True)
    body = (await client.get(ROUTE, headers=bearer(admin))).json()
    categories = [item["id"] for item in body["coverage"]["categories"]]
    assert {"secrets", "pii", "prompt_injection", "internal_network"} <= set(categories) and "pci" not in categories
    assert _cell(body, "prompt", "secrets")["text"] == "Refuse", "the platform invariant"
    assert _cell(body, "prompt", "pii")["text"] == "Scanned, no rule"
    assert _cell(body, "chat", "pii") == {"category": "pii", "outcome": "mask", "text": "Mask (platform)",
                                          "tone": "mask"}
    assert _cell(body, "chat", "prompt_injection")["text"] == "Refuse (platform)"
    assert _cell(body, "chat", "internal_network")["text"] == "Report (platform)"
    assert _cell(body, "commands", "secrets")["text"] == "Ask a person"
    assert _cell(body, "commands", "pii")["text"] == "Not scanned"
    assert _cell(body, "output", "secrets")["text"] == "Mask (platform)"
    assert _cell(body, "output", "prompt_injection")["text"] == "Not scanned"
    assert _cell(body, "ingest", "pii")["tone"] == "none"
    assert body["coverage"]["detectors"] >= 7 and body["edit_target"]["creates_draft"] is True
    platform = {item["id"]: item["outcome"] for item in body["coverage"]["platform_policies"]}
    assert platform == {"platform:prompt-injection-refused": "refuse", "platform:credentials-masked": "mask",
                        "platform:email-masked": "mask", "platform:internal-ip-reported": "report"}
    assert "message_filters" not in body["coverage"]
    member = await make_user(db, admin=False)
    assert (await client.get(ROUTE, headers=bearer(member))).status_code == 403
