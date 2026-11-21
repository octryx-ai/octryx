"""Which REST API version (``/rest/api/3`` or ``/rest/api/2``) a Jira instance answers, remembered per process.

Data Center answers 404 on ``/rest/api/3``, so trying it first on every request would double each search page
and connection check. The version that answered is remembered per instance URL and tried first; when it
stops answering (404), the other one is tried and remembered instead, so an upgraded or moved instance still
works. A not-found resource answers 404 on both versions and changes nothing.

Process memory only: a restart learns it again with the first request. No credential or response is kept.
"""

from __future__ import annotations

from urllib.parse import urlsplit

DEFAULT_ORDER: tuple[str, ...] = ("3", "2")
#: Bound on the remembered instances (a deployment has a handful); the oldest entry leaves first.
MAX_REMEMBERED = 256

_working_version: dict[str, str] = {}


def instance_key(jira_url: str) -> str:
    """The instance a URL names: scheme and host case-insensitive, path as given, without a trailing slash."""
    text = str(jira_url or "").strip().rstrip("/")
    parts = urlsplit(text)
    if not parts.scheme or not parts.netloc:
        return text
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path}"


def api_versions(jira_url: str) -> tuple[str, ...]:
    """The versions to try, the one that answered last time for this instance first."""
    remembered = _working_version.get(instance_key(jira_url))
    if remembered not in DEFAULT_ORDER:
        return DEFAULT_ORDER
    return (remembered, *(version for version in DEFAULT_ORDER if version != remembered))


def remember_api_version(jira_url: str, api_version: str) -> None:
    if api_version not in DEFAULT_ORDER:
        return
    key = instance_key(jira_url)
    _working_version.pop(key, None)
    _working_version[key] = api_version
    while len(_working_version) > MAX_REMEMBERED:
        _working_version.pop(next(iter(_working_version)))


def forget_api_versions() -> None:
    _working_version.clear()


__all__ = ["DEFAULT_ORDER", "api_versions", "forget_api_versions", "instance_key", "remember_api_version"]
