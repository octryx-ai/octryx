"""What the Teams plugin offers the admin: its identity and configuration fields."""

from typing import Any

PLUGIN_INFO: dict[str, Any] = {
    "id": "msteams",
    "name": "Microsoft Teams",
    "description": "Microsoft Teams Bot Framework channel plugin for sending and receiving messages",
    "version": "0.1.0",
    "author": "Octryx",
    "config_fields": [
        {
            "name": "app_id",
            "type": "string",
            "required": True,
            "description": "Azure Bot App ID (Application / Client ID)",
        },
        {
            "name": "app_password",
            "type": "string",
            "secret": True,
            "required": True,
            "description": "Azure Bot App Password (Client Secret)",
        },
        {
            "name": "tenant_id",
            "type": "string",
            "default": "botframework.com",
            "description": "Azure AD tenant ID (use 'botframework.com' for multi-tenant bots)",
        },
        {
            "name": "require_mention",
            "type": "boolean",
            "default": True,
            "description": "Only respond to messages that @mention the bot in group chats",
        },
        {
            "name": "thread_followup_policy",
            "type": "select",
            "options": ["mention_every_message", "mention_once_per_thread"],
            "default": "mention_once_per_thread",
            "description": "Allow follow-up messages in an already activated Teams thread without @mention",
        },
        {
            "name": "dm_policy",
            "type": "select",
            "options": ["open", "allowlist", "disabled"],
            "default": "allowlist",
            "description": "Policy for direct messages (personal conversations)",
        },
        {
            "name": "allow_from",
            "type": "list",
            "default": [],
            "description": "Allowed sender IDs for DMs when dm_policy is 'allowlist'",
        },
        {
            "name": "default_target",
            "type": "string",
            "default": "",
            "description": (
                "Default proactive target formatted as serviceUrl|conversationId for task output delivery"
            ),
        },
        {
            "name": "require_registered_user",
            "type": "boolean",
            "default": False,
            "description": "Only respond to senders mapped to an Octryx user",
        },
        {
            "name": "sender_mappings",
            "type": "string",
            "default": "",
            "description": (
                'JSON object mapping external sender IDs to platform user IDs, e.g. {"123": "user-uuid"}'
            ),
        },
        {
            "name": "allowed_roles",
            "type": "string",
            "default": "",
            "description": "Comma-separated role names allowed to use this channel (empty = all roles)",
        },
        {
            "name": "dev_mode",
            "type": "boolean",
            "default": False,
            "description": (
                "Skip the Azure token fetch (debug/local development only; blocked unless app "
                "debug mode is enabled). Inbound webhooks are still authenticated."
            ),
        },
        {
            "name": "calling_enabled",
            "type": "boolean",
            "default": False,
            "description": "Enable voice calling (Teams Calling / CallAgent)",
        },
        {
            "name": "calling_mode",
            "type": "select",
            "options": ["call_proxy", "graph_recording"],
            "default": "call_proxy",
            "description": (
                "Calling integration mode. call_proxy returns audioWebSocketUri for invited calls; "
                "graph_recording is experimental and requires Microsoft Graph communications permissions."
            ),
        },
        {
            "name": "calling_public_ws_url",
            "type": "string",
            "default": "",
            "description": "Public WebSocket URL for MediaBridge to connect (local dev: ngrok URL, e.g. wss://xxx.ngrok-free.dev; EKS: public cluster domain)",
        },
        {
            "name": "call_agent_thinking_message",
            "type": "string",
            "default": "One moment please, I'm looking into this.",
            "description": "Message played to the caller while the agent is processing.",
        },
        {
            "name": "call_require_wake_word",
            "type": "boolean",
            "default": True,
            "description": "Only respond when a configured wake word is present in the transcribed speech.",
        },
        {
            "name": "call_wake_words",
            "type": "string",
            "default": "hey octryx,octryx",
            "description": "Comma-separated wake words for Teams calls.",
        },
        {
            "name": "call_agent_max_tool_calls",
            "type": "number",
            "default": 5,
            "description": "Maximum number of tool calls the CallAgent can make per turn.",
        },
        {
            "name": "call_agent_system_prompt",
            "type": "string",
            "default": "You are a helpful meeting assistant. You help with status checks, questions about projects, and decisions. You can use tools to fetch information. Answer concisely and clearly, in the language the caller uses.",
            "description": "System prompt for the CallAgent voice assistant.",
        },
        {
            "name": "call_agent_llm_model",
            "type": "string",
            "default": "",
            "description": "LLM model override for the CallAgent (leave empty to use the control plane default).",
        },
        {
            "name": "call_agent_enabled_tools",
            "type": "string",
            "default": "",
            "description": "Comma-separated tool names the CallAgent may use (empty = no tools).",
        },
    ],
}
