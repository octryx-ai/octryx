"""PR review bot: the GitHub and Bitbucket Cloud APIs scripted per (method, path), every call recorded."""

from __future__ import annotations

import pytest

from app.tools.bitbucket_impl import _bitbucket_cloud_review as cloud_review
from app.tools.bitbucket_impl import _bitbucket_pr_review as bitbucket
from app.tools.connectors import github_pr_review as github


class Recorder:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def answer(self, method, path, body=None, params=None):
        self.calls.append((method, path, body, params))
        value = self.answers.get((method, path), {})
        if isinstance(value, Exception):
            raise value
        return value(params) if callable(value) else value


@pytest.fixture
def github_api(monkeypatch):
    api = Recorder({})

    async def http(method, url, *, headers=None, params=None, json_body=None, **_):
        return api.answer(method, url.removeprefix("https://api.github.test"), json_body, params)

    async def headers(_context):
        return {"Authorization": "Bearer test"}

    async def allowed(*_args, **_kwargs):
        return None

    monkeypatch.setattr(github, "_http_json", http)
    monkeypatch.setattr(github, "_github_headers", headers)
    monkeypatch.setattr(github, "_github_base_url", lambda _context: "https://api.github.test")
    monkeypatch.setattr(github, "require_github_repository_operation", allowed)
    return api


@pytest.fixture
def cloud_api(monkeypatch):
    api = Recorder({})

    async def request(_context, method, path, *, params=None, payload=None):
        return api.answer(method, path, payload, params)

    async def allowed(*_args, **_kwargs):
        return None

    monkeypatch.setattr(cloud_review, "cloud_request", request)
    monkeypatch.setattr(bitbucket, "cloud_context", lambda _context: True)
    monkeypatch.setattr(bitbucket, "_repository", lambda params, _context: (
        params["project_key"], params["repo_slug"], None))
    monkeypatch.setattr(bitbucket, "require_project_repository_operation", allowed)
    monkeypatch.setattr(bitbucket, "bitbucket_write_refusal", allowed)
    return api
