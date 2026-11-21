"""Where a capture may go: the base URL, the search path, the private output file, the request guard."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

from .library_inputs import is_identifier

CAPTURE_SCHEMA = "octryx.library_eval.capture/v1"
TOKEN_ENV = "OCTRYX_EVAL_TOKEN"
SEARCH_PATH = re.compile(r"^/api/v1/workspaces/[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}/knowledge/search$")
TITLE_CHARS = 120
EXCERPT_CHARS = 200
PROVIDER_USAGE = {"state": "unavailable", "reason": "not_exposed_by_search_api"}
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
RESPONSE_STATES = ("ok", "http_error", "malformed", "transport_error")
_HIT_TYPES = {
    "evidence_key": (str,), "source_id": (str, type(None)), "revision_id": (str, type(None)),
    "content_sha256": (str, type(None)), "workspace": (str, type(None)), "title": (str, type(None)),
    "excerpt": (str, type(None)), "bound": (bool, type(None)), "found_by": (list,),
}


class RefusedTargetError(ValueError):
    """The capture target or output location is not allowed."""


def check_base_url(base_url: str) -> str:
    """HTTPS anywhere, HTTP only on loopback; never userinfo, a path, a query or a fragment."""
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise RefusedTargetError("base URL must be http(s)://host[:port]")
    if parts.username or parts.password or "@" in parts.netloc:
        raise RefusedTargetError("base URL must not carry credentials")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise RefusedTargetError("base URL must not carry a path, query or fragment")
    if parts.scheme == "http":
        host = parts.hostname
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        if not loopback:
            raise RefusedTargetError("cleartext HTTP is only allowed for a loopback host")
    return f"{parts.scheme}://{parts.netloc}"


def check_private_output(path: str | Path) -> Path:
    """A capture holds real source content: refuse any location inside a git working tree."""
    target = Path(path).expanduser().resolve()
    for parent in (target.parent, *target.parent.parents):
        if (parent / ".git").exists():
            raise RefusedTargetError("captures are not written into a git working tree; use a private directory")
    return target


def search_path(project_id: str) -> str:
    if not is_identifier(project_id):
        raise RefusedTargetError("workspace id is not a valid identifier")
    path = f"/api/v1/workspaces/{quote(project_id, safe='')}/knowledge/search"
    if not SEARCH_PATH.match(path):
        raise RefusedTargetError("workspace id does not form an allowed search path")
    return path


def _guard(request: httpx.Request) -> None:
    """Defence in depth: the client may only ever POST to the search route."""
    if request.method != "POST" or not SEARCH_PATH.match(request.url.path):
        raise RefusedTargetError(f"refused {request.method} outside the search route")
