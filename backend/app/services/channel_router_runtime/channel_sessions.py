"""Channel sessions: which platform session a channel conversation continues, and who may use the channel."""

import logging

# Records keep the router's logger name.
logger = logging.getLogger("app.services.channel_router_runtime.service")


class ChannelSessionsMixin:
    _session_cache: dict[str, str]

    async def _cached_active_session(self, db, channel_key: str, user_id: str) -> str | None:
        from sqlalchemy import select

        from ...models.session.session import Session

        if channel_key in self._session_cache:
            cached_id = self._session_cache[channel_key]
            result = await db.execute(
                select(Session).where(
                    Session.id == cached_id,
                    Session.status.in_(("active", "pending_approval", "awaiting_subagents")),
                )
            )
            if result.scalar_one_or_none():
                return cached_id
            del self._session_cache[channel_key]

        result = await db.execute(
            select(Session).where(
                Session.user_id == user_id,
                Session.status.in_(("active", "pending_approval", "awaiting_subagents")),
            )
        )
        for session in result.scalars().all():
            meta = session.metadata_ or {}
            if meta.get("channel_key") == channel_key:
                self._session_cache[channel_key] = session.id
                return session.id
        return None

    async def _get_or_create_session(
        self,
        db,
        *,
        channel_id: str,
        channel_key: str,
        plugin_id: str,
        channel_name: str,
        sender_id: str,
        user_id: str,
        project_id: str | None,
        initial_content: str,
    ) -> str | None:
        from ...models.session.session import Session

        existing_id = await self._cached_active_session(db, channel_key, user_id)
        if existing_id is not None:
            return existing_id

        new_session = Session(
            user_id=user_id,
            project_id=project_id,
            agent_type="chat",
            status="active",
            origin="channel",
            metadata_={
                "channel": plugin_id,
                "channel_id": channel_id,
                "channel_name": channel_name,
                "sender_id": sender_id,
                "channel_key": channel_key,
                "conversation_id": channel_key.rsplit(":teams-thread:", 1)[-1]
                if ":teams-thread:" in channel_key
                else None,
                "channel_session": True,
                "title": self._infer_session_title(initial_content, channel_name, sender_id),
            },
        )
        db.add(new_session)
        await db.commit()
        await db.refresh(new_session)
        self._session_cache[channel_key] = new_session.id
        logger.info("Created channel session %s for %s", new_session.id, channel_key)
        return new_session.id

    def _build_channel_key(
        self,
        *,
        channel_id: str,
        plugin_id: str,
        sender_id: str,
        channel_type: str,
        conversation_id: str,
    ) -> str:
        if plugin_id == "msteams" and channel_type != "personal" and conversation_id:
            return f"{channel_id}:teams-thread:{conversation_id}"
        return f"{channel_id}:{sender_id}"

    async def _should_ignore_message_without_mention(
        self,
        db,
        *,
        channel_key: str,
        plugin_id: str,
        channel_type: str,
        plugin,
        msg: dict,
    ) -> bool:
        if plugin_id != "msteams" or channel_type == "personal":
            return False
        if not getattr(plugin, "require_mention", True):
            return False
        if msg.get("bot_mentioned"):
            return False
        if getattr(plugin, "thread_followup_policy", "") != "mention_once_per_thread":
            return True
        return not await self._has_active_channel_session(db, channel_key)

    async def _has_active_channel_session(self, db, channel_key: str) -> bool:
        from sqlalchemy import select

        from ...models.session.session import Session

        if channel_key in self._session_cache:
            cached_id = self._session_cache[channel_key]
            result = await db.execute(
                select(Session.id).where(
                    Session.id == cached_id,
                    Session.status.in_(("active", "pending_approval", "awaiting_subagents", "running")),
                )
            )
            if result.scalar_one_or_none():
                return True
            del self._session_cache[channel_key]

        result = await db.execute(
            select(Session.id).where(
                Session.status.in_(("active", "pending_approval", "awaiting_subagents", "running")),
                Session.metadata_["channel_key"].as_string() == channel_key,
            )
        )
        session_id = result.scalar_one_or_none()
        if session_id:
            self._session_cache[channel_key] = session_id
            return True
        return False

    async def _check_role_access(self, db, plugin, user_id: str) -> bool:
        from sqlalchemy import select

        from ...models.security.user import Role, UserRole

        if not plugin:
            return False
        allowed: list = getattr(plugin, "allowed_roles", [])
        if not allowed:
            return False

        if isinstance(allowed, str):
            allowed = [role.strip() for role in allowed.split(",") if role.strip()]
        if not allowed:
            return False

        result = await db.execute(
            select(Role.name).join(UserRole, Role.id == UserRole.role_id).where(UserRole.user_id == user_id)
        )
        user_roles = {row[0] for row in result.all()}
        allowed_set = {role.strip() for role in allowed}
        return not bool(user_roles & allowed_set)

    def _infer_session_title(self, content: str, channel_name: str, sender_id: str) -> str:
        normalized = " ".join((content or "").split()).strip()
        if normalized:
            return normalized[:80]
        return f"{channel_name} · {sender_id}"[:80]
