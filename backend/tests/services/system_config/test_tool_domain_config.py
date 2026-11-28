from __future__ import annotations

import json

import pytest

from app.models import SystemConfig
from app.services.system_config.constants import AGENT_TOOL_DOMAIN_CONFIG_KEY
from app.services.system_config.tool_domains import get_agent_tool_domain_config


@pytest.mark.asyncio
async def test_get_agent_tool_domain_config_uses_default_fallback_when_row_is_missing(db) -> None:
    config = await get_agent_tool_domain_config(db)

    assert "search_jira_tickets" in config["domain_tool_allowlists"]["jira"]
    assert "get_jira_ticket" in config["domain_tool_allowlists"]["jira"]
    assert "aws_read_operation" in config["domain_tool_allowlists"]["aws"]
    assert "aws_action_operation" in config["domain_tool_allowlists"]["aws"]
    assert "list_aws_codepipelines" in config["domain_tool_allowlists"]["aws"]
    assert config["summary_domain_tool_allowlists"]["bitbucket"] == ["list_recent_bitbucket_commits"]
    assert config["summary_tool_domains"]["search_confluence"] == ["confluence"]
    # The recorded Source Sync feed (K5) satisfies the Confluence domain next to the live search.
    assert sorted(config["summary_domain_satisfying_tools"]["confluence"]) == [
        "list_confluence_page_updates",
        "search_confluence",
    ]
    assert config["summary_tool_domains"]["list_confluence_page_updates"] == ["confluence"]


@pytest.mark.asyncio
async def test_get_agent_tool_domain_config_prefers_db_overrides_and_keeps_defaults_for_other_domains(db) -> None:
    db.add(
        SystemConfig(
            key=AGENT_TOOL_DOMAIN_CONFIG_KEY,
            value=json.dumps(
                {
                    "domain_tool_allowlists": {
                        "jira": ["custom_jira_lookup"],
                    },
                    "summary_domain_tool_allowlists": {
                        "confluence": ["custom_confluence_summary"],
                    },
                    "summary_tool_domains": {
                        "custom_confluence_digest": ["confluence"],
                    },
                    "summary_domain_satisfying_tools": {
                        "confluence": ["custom_confluence_summary"],
                    },
                },
                ensure_ascii=False,
            ),
        )
    )
    await db.commit()

    config = await get_agent_tool_domain_config(db)

    assert config["domain_tool_allowlists"]["jira"] == ["custom_jira_lookup"]
    assert "search_jira_tickets" not in config["domain_tool_allowlists"]["jira"]
    assert config["summary_domain_tool_allowlists"]["confluence"] == ["custom_confluence_summary"]
    assert config["summary_tool_domains"]["custom_confluence_digest"] == ["confluence"]
    assert config["summary_domain_satisfying_tools"]["confluence"] == ["custom_confluence_summary"]
    assert config["summary_domain_tool_allowlists"]["bitbucket"] == ["list_recent_bitbucket_commits"]
