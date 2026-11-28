"""Proactive Teams messaging — resolve users and initiate 1:1 conversations."""

import logging
import time
from typing import Any

import httpx

from app.services.person_log_ref import person_log_ref

logger = logging.getLogger(__name__)

_GRAPH_TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
_GRAPH_SCOPE = "https://graph.microsoft.com/.default"
_BF_SCOPE = "https://api.botframework.com/.default"


class ProactiveTeamsService:
    def __init__(
        self,
        app_id: str,
        app_password: str,
        tenant_id: str,
        service_url: str = "https://smba.trafficmanager.net/emea/",
    ):
        self.app_id = app_id
        self.app_password = app_password
        self.tenant_id = tenant_id
        self.service_url = service_url.rstrip("/")
        self._graph_token: str | None = None
        self._graph_token_expires_at: float = 0.0
        self._bf_token: str | None = None
        self._bf_token_expires_at: float = 0.0

    # ---------------------------------------------------------------- tokens

    async def _get_graph_token(self, client: httpx.AsyncClient) -> str:
        if self._graph_token and time.time() < self._graph_token_expires_at - 60:
            return self._graph_token

        token_url = _GRAPH_TOKEN_URL.format(tenant_id=self.tenant_id)
        resp = await client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.app_id,
                "client_secret": self.app_password,
                "scope": _GRAPH_SCOPE,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._graph_token = data["access_token"]
        self._graph_token_expires_at = time.time() + int(data.get("expires_in", 3600))
        return self._graph_token

    async def _get_bf_token(self, client: httpx.AsyncClient) -> str:
        if self._bf_token and time.time() < self._bf_token_expires_at - 60:
            return self._bf_token

        token_url = _GRAPH_TOKEN_URL.format(tenant_id=self.tenant_id)
        resp = await client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.app_id,
                "client_secret": self.app_password,
                "scope": _BF_SCOPE,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._bf_token = data["access_token"]
        self._bf_token_expires_at = time.time() + int(data.get("expires_in", 3600))
        return self._bf_token

    # ---------------------------------------------------------------- graph

    async def resolve_user_by_email(self, email: str) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=15) as client:
            token = await self._get_graph_token(client)
            resp = await client.get(
                f"https://graph.microsoft.com/v1.0/users/{email}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 404:
                logger.warning("Teams proactive: user not found for email=%s", email)
                return None
            resp.raise_for_status()
            data = resp.json()
            return {
                "id": data["id"],
                "displayName": data.get("displayName", ""),
                "mail": data.get("mail", email),
                "userPrincipalName": data.get("userPrincipalName", ""),
            }

    async def ensure_bot_installed_for_user(self, user_id: str) -> bool:
        async with httpx.AsyncClient(timeout=15) as client:
            token = await self._get_graph_token(client)
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

            # Check if already installed
            resp = await client.get(
                f"https://graph.microsoft.com/v1.0/users/{user_id}/teamwork/installedApps"
                f"?$expand=teamsAppDefinition&$filter=teamsAppDefinition/teamsAppId eq '{self.app_id}'",
                headers=headers,
            )
            if resp.status_code == 200:
                items = resp.json().get("value", [])
                if items:
                    logger.debug("Bot already installed for user %s", user_id)
                    return True

            # Install the bot for the user
            resp = await client.post(
                f"https://graph.microsoft.com/v1.0/users/{user_id}/teamwork/installedApps",
                headers=headers,
                json={"teamsApp@odata.bind": f"https://graph.microsoft.com/v1.0/appCatalogs/teamsApps/{self.app_id}"},
            )
            if resp.status_code in (200, 201, 204, 409):  # 409 = already installed
                logger.info("Bot installed for user %s", user_id)
                return True
            logger.warning("Failed to install bot for user %s: HTTP %s", user_id, resp.status_code)
            return False

    # ---------------------------------------------------------------- proactive message

    async def create_conversation_and_send(
        self,
        user_id: str,
        message: str,
    ) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=20) as client:
            token = await self._get_bf_token(client)

            payload = {
                "bot": {"id": self.app_id},
                "members": [{"id": user_id}],
                "channelData": {"tenant": {"id": self.tenant_id}},
                "isGroup": False,
                "activity": {"type": "message", "text": message},
                "tenantId": self.tenant_id,
            }

            url = f"{self.service_url}/v3/conversations"
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            )

            if resp.status_code not in (200, 201):
                logger.error(
                    "Proactive message failed for user %s: HTTP %s body_chars=%d",
                    person_log_ref(user_id),
                    resp.status_code,
                    len(resp.text or ""),
                )
                return None

            data = resp.json()
            conversation_id = data.get("id", "")
            logger.info("Proactive conversation created: %s for user %s", conversation_id, user_id)
            return {
                "conversation_id": conversation_id,
                "target": f"{self.service_url}|{conversation_id}",
                "activity_id": data.get("activityId", ""),
            }

    # ---------------------------------------------------------------- high-level

    async def send_proactive_message(self, email: str, message: str) -> dict[str, Any] | None:
        user = await self.resolve_user_by_email(email)
        if not user:
            return None

        installed = await self.ensure_bot_installed_for_user(user["id"])
        if not installed:
            logger.warning("Cannot send proactive message — bot not installed for user %s", user["id"])
            # Still try — some tenants pre-install the bot via policy
            pass

        result = await self.create_conversation_and_send(user["id"], message)
        if result:
            result["user"] = user
        return result
