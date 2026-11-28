"""Tool definitions for the HR, identity and calendar domain."""

from __future__ import annotations

import copy

# ruff: noqa: E501


HR_DEFINITIONS: dict[str, dict] = {
    "search_user": {
        "type": "function",
        "function": {
            "name": "search_user",
            "description": "Search users in LDAP or Active Directory by username, email or display name",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "username": {"type": "string"},
                    "email": {"type": "string"},
                    "limit": {"type": "integer"},
                    "timeout_sec": {"type": "integer"},
                },
            },
        },
    },
    "get_groups": {
        "type": "function",
        "function": {
            "name": "get_groups",
            "description": "List LDAP groups or the groups of a specific user",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {"type": "string"},
                    "user_dn": {"type": "string"},
                    "limit": {"type": "integer"},
                    "timeout_sec": {"type": "integer"},
                },
            },
        },
    },
    "check_membership": {
        "type": "function",
        "function": {
            "name": "check_membership",
            "description": "Check whether an LDAP user belongs to a specific group",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {"type": "string"},
                    "group_name": {"type": "string"},
                    "group_dn": {"type": "string"},
                    "timeout_sec": {"type": "integer"},
                },
                "required": ["username"],
            },
        },
    },
    "sync_users": {
        "type": "function",
        "function": {
            "name": "sync_users",
            "description": "Sync LDAP users and optionally provision them into the local Octryx user store",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "persist_local_users": {"type": "boolean"},
                    "roles": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer"},
                    "timeout_sec": {"type": "integer"},
                },
            },
        },
    },
    "user_provisioning": {
        "type": "function",
        "function": {
            "name": "user_provisioning",
            "description": "Provision or update a local Octryx user from LDAP data for onboarding workflows",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {"type": "string"},
                    "email": {"type": "string"},
                    "query": {"type": "string"},
                    "roles": {"type": "array", "items": {"type": "string"}},
                    "timeout_sec": {"type": "integer"},
                },
            },
        },
    },
    "get_free_busy": {
        "type": "function",
        "function": {
            "name": "get_free_busy",
            "description": "Read Outlook or Exchange free/busy information for configured mailboxes",
            "parameters": {
                "type": "object",
                "properties": {
                    "mailbox": {"type": "string"},
                    "mailboxes": {"type": "array", "items": {"type": "string"}},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "interval_minutes": {"type": "integer"},
                    "time_zone": {"type": "string"},
                },
            },
        },
    },
    "list_meetings": {
        "type": "function",
        "function": {
            "name": "list_meetings",
            "description": "List Outlook or Exchange calendar meetings for a mailbox",
            "parameters": {
                "type": "object",
                "properties": {
                    "mailbox": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "create_meeting": {
        "type": "function",
        "function": {
            "name": "create_meeting",
            "description": "Create an Outlook or Exchange meeting with approval gating",
            "parameters": {
                "type": "object",
                "properties": {
                    "mailbox": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "location": {"type": "string"},
                    "attendees": {"type": "array", "items": {"type": "string"}},
                    "online_meeting": {"type": "boolean"},
                    "time_zone": {"type": "string"},
                },
                "required": ["subject", "start", "end"],
            },
        },
    },
    "find_next_slot": {
        "type": "function",
        "function": {
            "name": "find_next_slot",
            "description": "Find the next free Outlook or Exchange calendar slot",
            "parameters": {
                "type": "object",
                "properties": {
                    "mailbox": {"type": "string"},
                    "mailboxes": {"type": "array", "items": {"type": "string"}},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "duration_minutes": {"type": "integer"},
                    "interval_minutes": {"type": "integer"},
                    "time_zone": {"type": "string"},
                },
            },
        },
    },
    "check_absence": {
        "type": "function",
        "function": {
            "name": "check_absence",
            "description": "Check whether a mailbox is marked as absent or out-of-office",
            "parameters": {
                "type": "object",
                "properties": {
                    "mailbox": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "send_meeting_invite": {
        "type": "function",
        "function": {
            "name": "send_meeting_invite",
            "description": "Create and send an Outlook or Exchange meeting invite with approval gating",
            "parameters": {
                "type": "object",
                "properties": {
                    "mailbox": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "location": {"type": "string"},
                    "attendees": {"type": "array", "items": {"type": "string"}},
                    "online_meeting": {"type": "boolean"},
                    "time_zone": {"type": "string"},
                },
                "required": ["subject", "start", "end", "attendees"],
            },
        },
    },
}


def get_hr_definitions() -> dict[str, dict]:
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(HR_DEFINITIONS)
