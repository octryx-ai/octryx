"""Expanding a Confluence read restriction to member email addresses. Read-only and bounded, at sync time."""

from __future__ import annotations

from urllib.parse import quote

from ...access.acl_keys import MAX_SOURCE_PRINCIPALS, normalize_email
from .contract import REASON_ACL_UNRESOLVED, REASON_SOURCE_NOT_FOUND, AclExpansion, AclFacet, ConnectorError
from .http import SourceReader

EXPANDABLE_RESTRICTIONS = frozenset({"page_restriction", "ancestor_restriction"})
MAX_GROUP_MEMBERS = MAX_SOURCE_PRINCIPALS
MAX_LOOKUPS_PER_RUN = 400
MEMBER_PAGE_SIZE = 50
# Label key -> the ``/rest/api/user`` query parameter that selects the account.
_USER_KEYS = {"username": "username", "userKey": "key", "accountId": "accountId"}


def _reported_email(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    personal = (payload.get("details") or {}).get("personal") if isinstance(payload.get("details"), dict) else None
    candidates = (payload.get("email"), personal.get("email") if isinstance(personal, dict) else None)
    return next((email for email in map(normalize_email, candidates) if email is not None), None)


def _user_ref(entry: object) -> str | None:
    if not isinstance(entry, dict):
        return None
    for key in _USER_KEYS:
        if entry.get(key):
            return f"{key}={entry[key]}"
    return None


class ConfluenceAclExpander:
    def __init__(self, reader: SourceReader) -> None:
        self._reader = reader
        self._emails: dict[str, str | None] = {}
        self._groups: dict[str, tuple[str | None, ...]] = {}
        self._lookups = 0

    def _count_lookup(self) -> None:
        self._lookups += 1
        if self._lookups > MAX_LOOKUPS_PER_RUN:
            raise ConnectorError(REASON_ACL_UNRESOLVED)

    async def expand(self, acl: AclFacet) -> AclExpansion | None:
        if acl.restriction not in EXPANDABLE_RESTRICTIONS:
            return None
        emails: set[str] = set()
        unmapped = 0
        for label in acl.principals:
            kind, _, value = str(label).partition(":")
            if kind == "user":
                members: tuple[str | None, ...] = (await self._email(value),)
            elif kind == "group":
                members = await self._members(value)
            else:
                raise ConnectorError(REASON_ACL_UNRESOLVED)
            for email in members:
                if email is None:
                    unmapped += 1
                else:
                    emails.add(email)
            if len(emails) > MAX_SOURCE_PRINCIPALS:
                raise ConnectorError(REASON_ACL_UNRESOLVED)
        return AclExpansion(member_emails=tuple(sorted(emails)), unmapped=unmapped)

    async def _email(self, user_ref: str) -> str | None:
        if user_ref in self._emails:
            return self._emails[user_ref]
        key, _, value = user_ref.partition("=")
        if key not in _USER_KEYS or not value:
            raise ConnectorError(REASON_ACL_UNRESOLVED)
        self._count_lookup()
        try:
            payload = await self._reader.get_json(
                "/rest/api/user", {_USER_KEYS[key]: value, "expand": "details.personal"}
            )
        except ConnectorError as error:
            if error.reason != REASON_SOURCE_NOT_FOUND:
                raise ConnectorError(REASON_ACL_UNRESOLVED) from None
            payload = None
        email = _reported_email(payload)
        if email is None and key == "accountId":
            # Cloud: an accountId-only principal with no visible address can never be matched.
            raise ConnectorError(REASON_ACL_UNRESOLVED)
        self._emails[user_ref] = email
        return email

    async def _members(self, group: str) -> tuple[str | None, ...]:
        if group in self._groups:
            return self._groups[group]
        if not group or group in (".", ".."):
            raise ConnectorError(REASON_ACL_UNRESOLVED)
        path = f"/rest/api/group/{quote(group, safe='')}/member"
        members: list[str | None] = []
        start = 0
        while True:
            self._count_lookup()
            try:
                payload = await self._reader.get_json(path, {"start": start, "limit": MEMBER_PAGE_SIZE})
            except ConnectorError:
                raise ConnectorError(REASON_ACL_UNRESOLVED) from None
            results = payload.get("results")
            if not isinstance(results, list) or len(results) > MEMBER_PAGE_SIZE:
                raise ConnectorError(REASON_ACL_UNRESOLVED)
            for entry in results:
                reported = _reported_email(entry)
                ref = _user_ref(entry)
                if reported is None and ref is None:
                    raise ConnectorError(REASON_ACL_UNRESOLVED)
                members.append(reported if reported is not None else await self._email(ref))
            if len(members) > MAX_GROUP_MEMBERS:
                raise ConnectorError(REASON_ACL_UNRESOLVED)
            if not results or "next" not in (payload.get("_links") or {}):
                break
            start += len(results)
        self._groups[group] = tuple(members)
        return self._groups[group]


__all__ = ["ConfluenceAclExpander", "EXPANDABLE_RESTRICTIONS"]
