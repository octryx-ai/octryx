"""Loads the standalone source-system stubs under their sibling names and puts a stub's ``handle`` behind an
``httpx.MockTransport``, so the real connectors talk to what the acceptance stack serves."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from urllib.parse import urlsplit

import httpx

STUB_DIR = pathlib.Path(__file__).resolve().parent / "fixtures" / "source_stubs"


def load(name: str, path: pathlib.Path | None = None):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path or STUB_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Dependencies first: the stubs import these by module name.
stub_http = load("stub_http")
confluence_fixtures = load("confluence_fixtures")
jira_fixtures = load("jira_fixtures")
confluence_stub = load("confluence_stub")
jira_stub = load("jira_stub")
acceptance_http = load("octryx_acceptance_http", STUB_DIR / "acceptance_http.py")


def transport(stub, base_url: str, requests: list[str] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert f"{request.url.scheme}://{request.url.netloc.decode()}" == base_url
        target = request.url.raw_path.decode()
        if requests is not None:
            requests.append(f"{request.method} {urlsplit(target).path}")
        status, payload = stub.handle(request.method, target, request.headers.get("Authorization"))
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)
