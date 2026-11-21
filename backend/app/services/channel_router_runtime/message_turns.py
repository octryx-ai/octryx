"""One inbound channel message: the checks it passes, the agent turn it runs, and the reply it sends."""

import logging
import uuid
from dataclasses import dataclass

from app.services.error_facts import error_text
from app.services.run_capability.worker_profiles import worker_session_capability_metadata

from .approval_commands import SENDER_UNRESOLVED_REPLY, is_approval_command
from .run_as import resolve_run_as_user
from .sender_identity import resolve_sender_user_id

# Records keep the router's logger name.
logger = logging.getLogger("app.services.channel_router_runtime.service")


@dataclass(frozen=True)
class InboundMessage:
    """The facts of one inbound message the router reads from the plugin and the message."""

    channel_id: str
    plugin_id: str
    channel_name: str
    project_id: str | None
    sender_id: str
    content: str
    channel_type: str
    conversation_id: str
    channel_key: str


class ChannelTurnsMixin:
    """Message handling of the channel router; the host class provides the session and access helpers."""

    def _inbound_message(self, channel_id: str, plugin, msg: dict) -> InboundMessage:
        plugin_id = str(plugin.plugin_id)
        channel_name = str(plugin.config.get("__channel_name") or plugin_id)
        project_id = str(plugin.config.get("__channel_project_id") or "").strip() or None
        sender_id = str(msg.get("sender_id") or "unknown")
        content = (msg.get("content") or "").strip()
        channel_type = str(msg.get("channel_type") or "")
        conversation_id = str(msg.get("conversation_id") or "").strip()
        channel_key = self._build_channel_key(
            channel_id=channel_id,
            plugin_id=plugin_id,
            sender_id=sender_id,
            channel_type=channel_type,
            conversation_id=conversation_id,
        )
        return InboundMessage(
            channel_id, plugin_id, channel_name, project_id, sender_id, content, channel_type, conversation_id,
            channel_key,
        )

    async def _handle_message(self, channel_id: str, plugin, msg: dict) -> None:
        inbound = self._inbound_message(channel_id, plugin, msg)
        channel_key = inbound.channel_key

        if not inbound.content:
            return

        logger.info("[%s] → %s", channel_key, inbound.content[:120])

        try:
            async with self._session_factory() as db:
                response_parts = await self._route_message(db, plugin, msg, inbound)
                if response_parts is None:
                    return

            response = "".join(response_parts).strip()
            if response:
                target = str(msg.get("target") or inbound.sender_id)
                success = await plugin.send_message(target, response)
                if success:
                    logger.info("[%s] ← %s", channel_key, response[:120])
                else:
                    logger.warning("[%s] send_message returned False", channel_key)

        except Exception as exc:
            logger.exception("Error handling message from %s: %s", channel_key, exc)

    async def _route_message(self, db, plugin, msg: dict, inbound: InboundMessage) -> list[str] | None:
        """Run the checks in order; ``None`` when one of them answered or refused, else the turn's reply parts."""
        channel_key, content, sender_id = inbound.channel_key, inbound.content, inbound.sender_id
        # Check if this is a reply to a proactive conversation (e.g. Jira reporter answering)
        if inbound.conversation_id and await self._check_proactive_reply(
            db, inbound.conversation_id, content, sender_id, plugin, msg
        ):
            return None

        if await self._should_ignore_message_without_mention(
            db, channel_key=channel_key, plugin_id=inbound.plugin_id, channel_type=inbound.channel_type,
            plugin=plugin, msg=msg,
        ):
            return None

        target = str(msg.get("target") or sender_id)
        sender_user_id = await resolve_sender_user_id(db, plugin, sender_id)
        if sender_user_id is None and is_approval_command(content):
            # An unresolved sender never decides, whatever the channel runs it as.
            await plugin.send_message(target, SENDER_UNRESOLVED_REPLY)
            return None
        run_as = await resolve_run_as_user(
            db, plugin, channel_id=inbound.channel_id, project_id=inbound.project_id, resolved=sender_user_id
        )
        if run_as.user_id is None:
            logger.info("[%s] channel message refused: %s", channel_key, run_as.state)
            if run_as.reply:
                await plugin.send_message(target, run_as.reply)
            return None
        user_id = run_as.user_id

        denied = await self._check_role_access(db, plugin, user_id)
        if denied:
            await plugin.send_message(
                target,
                "You do not have permission to use this channel.",
            )
            logger.info("[%s] RBAC denied for user %s", channel_key, user_id)
            return None

        # Only the sender's own platform user decides, never the channel's service user.
        approval_response = await self._handle_approval_command(db, content, sender_user_id)
        if approval_response is not None:
            await plugin.send_message(target, approval_response)
            return None

        session_id = await self._get_or_create_session(
            db, channel_id=inbound.channel_id, channel_key=channel_key, plugin_id=inbound.plugin_id,
            channel_name=inbound.channel_name, sender_id=sender_id, user_id=user_id,
            project_id=inbound.project_id, initial_content=content,
        )
        if not session_id:
            return None
        return await self._run_turn(db, inbound, session_id=session_id, user_id=user_id)

    def _turn_metadata(self, session_obj, inbound: InboundMessage) -> dict:
        metadata = dict(session_obj.metadata_ or {})
        metadata["channel"] = inbound.plugin_id
        metadata["channel_id"] = inbound.channel_id
        metadata["channel_name"] = inbound.channel_name
        metadata["channel_key"] = inbound.channel_key
        metadata["sender_id"] = inbound.sender_id
        if inbound.conversation_id:
            metadata["conversation_id"] = inbound.conversation_id
        if inbound.channel_type:
            metadata["channel_type"] = inbound.channel_type
        metadata["channel_session"] = True
        metadata.update(worker_session_capability_metadata("channel_router"))
        metadata["title"] = metadata.get("title") or self._infer_session_title(
            inbound.content,
            inbound.channel_name,
            inbound.sender_id,
        )
        return metadata

    async def _run_turn(self, db, inbound: InboundMessage, *, session_id: str, user_id: str) -> list[str] | None:
        from ...agent.engine import AgentEvent, run_agent
        from ...models.session.session import Message, Session
        from ..session.turn_owner import claim_turn_ownership

        response_parts: list[str] = []
        events: list[AgentEvent] = []
        session_obj = await db.get(Session, session_id)
        if session_obj is None:
            return None

        session_obj.status = "running"
        session_obj.ended_at = None
        claim_turn_ownership(session_obj)
        metadata = self._turn_metadata(session_obj, inbound)
        user_msg = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role="user",
            content=inbound.content,
        )
        db.add(user_msg)
        metadata["current_turn_user_message_id"] = user_msg.id
        session_obj.metadata_ = metadata
        await db.commit()

        async for event in run_agent(
            session_id=session_id,
            user_message=inbound.content,
            user_id=user_id,
            project_id=session_obj.project_id,
            agent_type="chat",
            db=db,
        ):
            if event.role == "assistant" and event.content:
                response_parts.append(event.content)
            events.append(event)

        await self._record_turn_usage(db, session_obj, events)
        return response_parts

    async def _record_turn_usage(self, db, session_obj, events: list) -> None:
        try:
            total_tokens_in = sum(e.tokens_in for e in events if hasattr(e, "tokens_in"))
            total_tokens_out = sum(e.tokens_out for e in events if hasattr(e, "tokens_out"))
            total_cost = sum(e.cost for e in events if hasattr(e, "cost"))
            meta = dict(session_obj.metadata_ or {})
            meta["total_tokens_in"] = meta.get("total_tokens_in", 0) + total_tokens_in
            meta["total_tokens_out"] = meta.get("total_tokens_out", 0) + total_tokens_out
            meta["total_cost"] = meta.get("total_cost", 0.0) + total_cost
            meta["message_count"] = meta.get("message_count", 0) + 1
            meta.pop("current_turn_user_message_id", None)
            session_obj.metadata_ = meta
            if session_obj.status not in {"pending_approval", "awaiting_subagents"}:
                session_obj.status = "active"
            await db.commit()
        except Exception as stats_exc:
            logger.warning(
                "Failed to update session usage stats: %s", error_text("session_usage_stats_update_failed", stats_exc)
            )
