"""Confluence listing helpers: canonical page links, listing tokens and read restrictions."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit

from ...ledger.errors import InvalidEvidenceRequestError
from ..source_url import normalize_source_url
from .contract import REASON_SOURCE_CONTRACT_VIOLATION, ConnectorError

_LIST_EXPAND = "version,ancestors,restrictions.read.restrictions.user,restrictions.read.restrictions.group"
MAX_TITLE_CHARS = 300
MAX_WEBUI_CHARS = 1000
CQL_TIME_FORMAT = "%Y-%m-%d %H:%M"


def _same_origin(left: str, right: str) -> bool:
    a, b = urlsplit(left), urlsplit(right)
    return (a.scheme.lower(), (a.hostname or "").lower(), a.port) == (
        b.scheme.lower(),
        (b.hostname or "").lower(),
        b.port,
    )


def canonical_page_url(
    base_url: str, page_id: object, *, webui: object = None, response_base: object = None
) -> str | None:
    # ``response_base`` is used only on the configured origin, so a response can never point a link at another host.
    identifier = str(page_id or "").strip()
    base = str(base_url or "").strip().rstrip("/")
    try:
        if not identifier.isdigit() or normalize_source_url(base) is None:
            return None
        fallback = normalize_source_url(f"{base}/pages/viewpage.action?pageId={identifier}")
    except InvalidEvidenceRequestError:
        return None  # the configured base itself is unusable
    try:
        if type(response_base) is str and normalize_source_url(response_base) and _same_origin(response_base, base):
            base = response_base.strip().rstrip("/")
    except (ValueError, InvalidEvidenceRequestError):
        pass  # a malformed base or port in the response: the configured base
    relative = type(webui) is str and webui.startswith("/") and not webui.startswith("//")
    if relative and len(webui) <= MAX_WEBUI_CHARS:
        try:
            return normalize_source_url(f"{base}{webui}") or fallback
        except (ValueError, InvalidEvidenceRequestError):
            pass  # a malformed path: the id link on the configured base
    return fallback


def _parse_token(token: str | None) -> tuple[int, int | str]:
    if token is None:
        return 0, 0
    head, _, rest = token.partition(":")
    try:
        index = int(head)
    except ValueError:
        raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION) from None
    if index < 0:
        raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
    if rest.startswith("/"):
        return index, rest
    try:
        offset = int(rest)
    except ValueError:
        raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION) from None
    if offset < 0:
        raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
    return index, offset


def _with_limit(link: str, limit: int) -> str:
    route, _, query = link.partition("?")
    pairs = [(key, value) for key, value in parse_qsl(query, keep_blank_values=True) if key != "limit"]
    return f"{route}?{urlencode([*pairs, ('limit', str(limit))])}"


def _principals(read: object) -> tuple[str, ...] | None:
    if not isinstance(read, dict) or not isinstance(read.get("restrictions"), dict):
        return None
    restrictions = read["restrictions"]
    names: list[str] = []
    for kind, keys in (("user", ("username", "userKey", "accountId")), ("group", ("name",))):
        bucket = restrictions.get(kind) or {}
        results = bucket.get("results") if isinstance(bucket, dict) else None
        if results is None:
            results = []
        if not isinstance(results, list):
            return None
        for entry in results:
            found = next((key for key in keys if isinstance(entry, dict) and entry.get(key)), None)
            if found is None:
                names.append(f"{kind}:")
            elif kind == "user":
                names.append(f"user:{found}={entry[found]}")
            else:
                names.append(f"group:{entry[found]}")
    return tuple(names)

