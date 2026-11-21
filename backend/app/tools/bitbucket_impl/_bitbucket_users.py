"""Bitbucket user lookup tools.

Server/Data Center: users by a ``filter`` (username, display name, email). Bitbucket Cloud has no user search; there
the tool reads one account by its Atlassian ``account_id`` (``GET /users/<account id>``; it verifies a linked account,
``services/linked_accounts``).
"""

from typing import Any
from urllib.parse import quote

from app.tools.context import ToolContext

from . import _bitbucket_internal_network
from ._bitbucket_cloud import CloudApiError, cloud_context, cloud_failure, cloud_request
from ._bitbucket_internal_core import _bitbucket_base_url


def _bitbucket_user_summary(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": user.get("name"),
        "display_name": user.get("displayName"),
        "email_address": user.get("emailAddress"),
        "slug": user.get("slug"),
        "active": user.get("active"),
        "type": user.get("type"),
    }


async def _cloud_account(context: ToolContext, account_id: str) -> dict[str, Any]:
    if not account_id:
        return {"error": "Bitbucket Cloud looks a user up by account_id only"}
    try:
        user = await cloud_request(context, "GET", f"/users/{quote(account_id, safe='')}")
    except CloudApiError as error:
        if error.status != 404:
            return cloud_failure(error)
        user = None
    known = isinstance(user, dict) and account_id in (user.get("account_id"), user.get("uuid"))
    users = [{"account_id": user.get("account_id"), "uuid": user.get("uuid"), "display_name": user.get("display_name"),
              "name": user.get("nickname"), "active": True}] if known else []
    return {"account_id": account_id, "total": len(users), "users": users}


class SearchBitbucketUsers:
    name = "search_bitbucket_users"
    description = "Search Bitbucket users by username, display name, or email for author-based evidence lookup."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        account_id = str(params.get("account_id") or "").strip()
        if cloud_context(context):
            return await _cloud_account(context, account_id)
        if account_id:
            return {"error": "A lookup by account id needs a Bitbucket Cloud connection (Atlassian accounts)."}
        if not _bitbucket_base_url(context):
            return {"error": "No Bitbucket URL configured for this project"}

        query = str(params.get("query") or params.get("username") or params.get("email") or "").strip()
        if not query:
            return {"error": "query is required"}
        limit = max(1, min(int(params.get("limit") or 10), 50))

        payload = await _bitbucket_internal_network._bitbucket_json_get(
            context,
            "/rest/api/1.0/users",
            params={"filter": query, "limit": limit},
        )
        users = payload.get("values") if isinstance(payload.get("values"), list) else []
        return {
            "query": query,
            "total": len(users),
            "users": [_bitbucket_user_summary(user) for user in users if isinstance(user, dict)],
        }
