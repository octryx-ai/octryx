"""Teams messages: sending to conversations and threads, receiving and mention handling."""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class TeamsMessaging:
    async def send_message(self, target: str, content: str, **kwargs) -> bool:
        if not self._http_client:
            logger.error("Teams plugin: not initialised")
            return False

        try:
            token = await self._ensure_token()
            if target.startswith("thread|"):
                return await self._create_channel_thread(target, content, token)
            return await self._send_existing_conversation_message(target, content, token)
        except Exception as e:
            logger.exception("Teams send_message error: %s", e)
            return False
    async def _send_existing_conversation_message(self, target: str, content: str, token: str) -> bool:
        parts = target.split("|", 1)
        if len(parts) != 2:
            logger.error(
                "Teams send_message: target must be 'serviceUrl|conversationId' or "
                "'thread|serviceUrl|tenantId|teamId|channelId'"
            )
            return False
        service_url, conversation_id = parts
        url = f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}/activities"
        assert self._http_client is not None
        resp = await self._http_client.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"type": "message", "text": content},
        )
        resp.raise_for_status()
        logger.debug("Teams message sent to conversation %s", conversation_id)
        return True
    async def _create_channel_thread(self, target: str, content: str, token: str) -> bool:
        parts = target.split("|")
        if len(parts) != 5:
            logger.error("Teams thread target must be 'thread|serviceUrl|tenantId|teamId|channelId'")
            return False
        _, service_url, tenant_id, team_id, channel_id = parts
        if not all((service_url, tenant_id, team_id, channel_id)):
            logger.error("Teams thread target contains empty serviceUrl, tenantId, teamId, or channelId")
            return False

        url = f"{service_url.rstrip('/')}/v3/conversations"
        bot_name = str(self.config.get("__channel_name") or self.config.get("name") or "Octryx")
        payload = {
            "isGroup": True,
            "bot": {"id": self.app_id, "name": bot_name},
            "activity": {"type": "message", "text": content},
            "channelData": {
                "tenant": {"id": tenant_id},
                "team": {"id": team_id},
                "channel": {"id": channel_id},
                "teamsTeamId": team_id,
                "teamsChannelId": channel_id,
            },
        }
        assert self._http_client is not None
        resp = await self._http_client.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        logger.debug("Teams channel thread created for team %s channel %s", team_id, channel_id)
        return True
    async def receive_message(self) -> dict[str, Any] | None:
        try:
            return self._message_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None
    @staticmethod
    def _strip_mentions(text: str, entities: list[dict]) -> str:
        import re as _re

        for entity in entities:
            if entity.get("type") == "mention":
                mention_text = entity.get("text", "")
                if mention_text:
                    text = text.replace(mention_text, "")
        # Catch any remaining <at>...</at> tags
        text = _re.sub(r"<at>[^<]*</at>", "", text)
        return text.strip()
    def _bot_was_mentioned(self, payload: dict) -> bool:
        bot_id = payload.get("recipient", {}).get("id", "")
        for entity in payload.get("entities", []):
            if entity.get("type") == "mention":
                if entity.get("mentioned", {}).get("id") == bot_id:
                    return True
        return False
