"""The Bitbucket Server URL, token, credential builders, tool context and token world shared by the auth mode tests."""

from __future__ import annotations

import base64

import pytest

from app.tools.bitbucket_impl import _bitbucket_internal_network as network
from app.tools.context import ToolContext
from tests.support.oidc_stub_support import IDP, SECRET, stub_world

BB_URL = "https://bb.test/bitbucket"


PAT = "pat-0123456789"


def _basic(user: str, secret: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{secret}".encode()).decode()


def _oidc(**extra) -> dict:
    return {"bitbucket_url": BB_URL, "bitbucket_auth_mode": "oidc_client_credentials",
            "bitbucket_oidc_token_url": IDP, "bitbucket_oidc_client_id": "octryx-client",
            "bitbucket_oidc_client_secret": SECRET,
            "bitbucket_allowed_repos": [{"project_key": "RIVER", "repo_slug": "ledger", "enabled": True}], **extra}


def _pat(**extra) -> dict:
    return {"bitbucket_url": BB_URL, "bitbucket_auth_mode": "bearer_pat", "bitbucket_token": PAT,
            "bitbucket_allowed_repos": [{"project_key": "RIVER", "repo_slug": "ledger", "enabled": True}], **extra}


def _context(config: dict, **extra) -> ToolContext:
    return ToolContext(user_id="u1", project_ids=[], roles=["admin"], session_id="s1", project_config=config,
                       **{"workspace_root": "/tmp", **extra})


@pytest.fixture
def world(monkeypatch):
    import app.services.design_delivery_sync.bitbucket_fetch as fetch
    import app.services.repository_bootstrap.providers as providers
    import app.tools.bitbucket_impl._bitbucket_repository_base as repository_base

    for state in stub_world(monkeypatch):
        def transport(*_args, inner=None, **_kwargs):
            return inner or state.transport()

        for module in (network, repository_base, fetch, providers):
            monkeypatch.setattr(module, "egress_transport", transport)
        yield state
