"""Tool definitions for clarification domain."""

from __future__ import annotations

import copy

from ..outbound_message_contract import MAX_QUESTION_CHARS, MAX_RECIPIENT_CHARS, MAX_TICKET_ID_CHARS

CLARIFICATION_DEFINITIONS: dict[str, dict] = {
    "ask_clarification": {
        "type": "function",
        "function": {
            "name": "ask_clarification",
            "description": (
                "Pause the run and ask the user a question in the chat (ambiguous scope, missing information, "
                "conflicting constraints, a decision). The run resumes when the user answers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question for the user.",
                    },
                    "question_id": {
                        "type": "string",
                        "description": "A stable key, e.g. 'scope-missing'; an open or answered one is reused.",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "default": "medium",
                        "description": "Urgency level of the clarification.",
                    },
                    "context_snapshot": {
                        "type": "object",
                        "description": (
                            "Optional run-state snapshot (messages, thread context) to restore when resuming. "
                            "If omitted, the run resumes with the answer as the next user message."
                        ),
                    },
                },
                "required": ["question", "question_id"],
            },
        },
    },
    # Outbound: a direct Teams message to a person outside the session (write risk, see write_risk.py).
    "ask_reporter_via_teams": {
        "type": "function",
        "function": {
            "name": "ask_reporter_via_teams",
            "description": (
                "Send a clarification question to a Jira ticket's reporter as a direct Microsoft Teams message. "
                "The reply is added back to this session; the run pauses until it arrives. "
                "Use this only when the ticket lacks information needed to proceed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "string",
                        "maxLength": MAX_TICKET_ID_CHARS,
                        "description": "The Jira ticket key, e.g. BRD-8.",
                    },
                    "reporter_email": {
                        "type": "string",
                        "maxLength": MAX_RECIPIENT_CHARS,
                        "description": "The reporter's email address, from get_jira_ticket (one address).",
                    },
                    "question": {
                        "type": "string",
                        "maxLength": MAX_QUESTION_CHARS,
                        "description": "One specific question for the reporter; a person approves it as written.",
                    },
                },
                "required": ["ticket_id", "reporter_email", "question"],
            },
        },
    },
}


def get_clarification_definitions() -> dict[str, dict]:
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(CLARIFICATION_DEFINITIONS)
