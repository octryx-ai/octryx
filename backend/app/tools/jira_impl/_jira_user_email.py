"""An Atlassian account by its email or its account id, on a Jira Cloud connection (``search_jira_users`` with ``email``
/ ``account_id``; the account id lookup verifies a linked account, ``services/linked_accounts``)."""

from __future__ import annotations

from typing import Any

import httpx

MAX_CANDIDATES = 10


def matching_accounts(users: list[Any], email: str) -> list[dict[str, Any]]:
    wanted = email.strip().lower()
    accounts = [user for user in users if isinstance(user, dict) and user.get("accountId")
                and user.get("accountType", "atlassian") == "atlassian" and user.get("active", True)]
    exact = [user for user in accounts if str(user.get("emailAddress") or "").strip().lower() == wanted]
    return exact if len(exact) == 1 else []


async def accounts_by_email(
    client: httpx.AsyncClient, jira_url: str, *, headers: dict[str, str], email: str
) -> list[dict[str, Any]]:
    response = await client.get(f"{jira_url}/rest/api/3/user/search", headers=headers,
                                params={"query": email.strip(), "maxResults": MAX_CANDIDATES})
    if response.status_code >= 400:
        return []
    payload = response.json() if response.content else []
    return matching_accounts(payload if isinstance(payload, list) else [], email)


async def account_by_id(
    client: httpx.AsyncClient, jira_url: str, *, headers: dict[str, str], account_id: str
) -> list[dict[str, Any]]:
    response = await client.get(f"{jira_url}/rest/api/3/user", headers=headers,
                                params={"accountId": account_id.strip()})
    if response.status_code >= 400:
        return []
    user = response.json() if response.content else {}
    known = isinstance(user, dict) and user.get("accountId") == account_id.strip() and user.get("active", True)
    return [user] if known else []


__all__ = ["account_by_id", "accounts_by_email", "matching_accounts"]
