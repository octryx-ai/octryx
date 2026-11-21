"""Agent tool: ask the Jira reporter a question via Teams proactive messaging.

This tool allows the agent to send a clarification question to a Jira ticket's
reporter via Microsoft Teams. The conversation is tracked so that when the
reporter replies, the answer is routed back to the agent session.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from ..context import ToolContext
from ..outbound_message_contract import outbound_message_refusal

logger = logging.getLogger(__name__)


class AskReporterViaTeams:
    name = "ask_reporter_via_teams"
    description = (
        "Send a clarification question to a Jira ticket's reporter via Microsoft Teams. "
        "The reporter will receive a direct message. Their reply will be captured and "
        "added back to this session. Use this when a ticket lacks information needed "
        "to proceed. Params: ticket_id (str), reporter_email (str), question (str)."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        ticket_id = str(params.get("ticket_id") or "").strip()
        reporter_email = str(params.get("reporter_email") or "").strip()
        question = str(params.get("question") or "").strip()

        if not ticket_id:
            return {"error": "ticket_id is required"}
        if not reporter_email:
            return {"error": "reporter_email is required — use get_jira_ticket to obtain it"}
        if not question:
            return {"error": "question is required"}
        refusal = outbound_message_refusal(self.name, params)
        if refusal is not None:
            return refusal

        # Resolve channel config for Teams
        from sqlalchemy import select

        from ...models.integration.channel_config import ChannelConfig

        project_id = context.project_ids[0] if context.project_ids else None
        if not project_id:
            return {"error": "No project context available"}

        db = context.db
        if not db:
            return {"error": "Database session not available"}

        result = await db.execute(
            select(ChannelConfig).where(
                ChannelConfig.plugin_id == "msteams",
                ChannelConfig.project_id == project_id,
                ChannelConfig.enabled.is_(True),
            )
        )
        configs = list(result.scalars().all())
        if not configs:
            return {"error": "No Teams channel configured for this project"}

        config = configs[0]
        import json

        channel_data = json.loads(config.config) if isinstance(config.config, str) else config.config
        app_id = channel_data.get("app_id", "")
        app_password = channel_data.get("app_password", "")
        tenant_id = channel_data.get("tenant_id", "botframework.com")
        service_url = channel_data.get("service_url", "https://smba.trafficmanager.net/emea/")

        if not app_id or not app_password:
            return {"error": "Teams channel not properly configured (missing app_id/app_password)"}

        # Send proactive message
        from ...services.proactive_teams.proactive_teams_service import ProactiveTeamsService

        svc = ProactiveTeamsService(
            app_id=app_id,
            app_password=app_password,
            tenant_id=tenant_id,
            service_url=service_url,
        )

        # Format the outbound message
        message = (
            f"📋 **Question about ticket {ticket_id}**\n\n"
            f"{question}\n\n"
            f"_Please reply directly to this message — "
            f"your answer is added to the ticket automatically._"
        )

        result = await svc.send_proactive_message(reporter_email, message)
        if not result:
            return {
                "error": f"Could not reach reporter {reporter_email} via Teams. "
                "The user may not exist in the tenant or the bot lacks permissions."
            }

        # Persist the conversation binding
        from ...models.integration.proactive_conversation import ProactiveConversation

        conv = ProactiveConversation(
            project_id=project_id,
            channel_config_id=str(config.id),
            ticket_id=ticket_id,
            reporter_email=reporter_email,
            teams_user_id=result["user"]["id"],
            conversation_id=result["conversation_id"],
            service_url=service_url,
            target=result["target"],
            session_id=context.session_id,
            question=question,
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(hours=48),
        )
        db.add(conv)
        await db.commit()

        logger.info(
            "Proactive question sent for ticket %s to %s (conv=%s, session=%s)",
            ticket_id,
            reporter_email,
            result["conversation_id"],
            context.session_id,
        )

        return {
            "success": True,
            "message": f"Question sent to {reporter_email} via Teams.",
            "conversation_id": result["conversation_id"],
            "ticket_id": ticket_id,
            "status": "paused",
            "paused": True,
            "waiting_for_reply": True,
            "hint": (
                "The agent session will be resumed when the reporter replies. "
                "Do not proceed until the reply arrives."
            ),
        }
