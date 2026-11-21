"""Tool definitions for the infrastructure automation domain."""

from __future__ import annotations

import copy

# ruff: noqa: E501
from .infrastructure_delivery import INFRASTRUCTURE_DELIVERY_DEFINITIONS

_SECRETS_AUTOMATION_DEFINITIONS: dict[str, dict] = {
    "read_secret": {
        "type": "function",
        "function": {
            "name": "read_secret",
            "description": "Read a secret from HashiCorp Vault for an allowed path",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "version": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    "list_secrets": {
        "type": "function",
        "function": {
            "name": "list_secrets",
            "description": "List secret keys from HashiCorp Vault for an allowed path",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    "renew_lease": {
        "type": "function",
        "function": {
            "name": "renew_lease",
            "description": "Renew a HashiCorp Vault lease",
            "parameters": {
                "type": "object",
                "properties": {
                    "lease_id": {"type": "string"},
                    "increment_seconds": {"type": "integer"},
                },
                "required": ["lease_id"],
            },
        },
    },
    "revoke_token": {
        "type": "function",
        "function": {
            "name": "revoke_token",
            "description": "Revoke a HashiCorp Vault token or revoke the current token",
            "parameters": {
                "type": "object",
                "properties": {
                    "token": {"type": "string"},
                },
            },
        },
    },
    "audit_log_read": {
        "type": "function",
        "function": {
            "name": "audit_log_read",
            "description": "Read HashiCorp Vault audit information from the configured endpoint",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "list_inventory": {
        "type": "function",
        "function": {
            "name": "list_inventory",
            "description": "List Ansible inventory groups and hosts",
            "parameters": {"type": "object", "properties": {"timeout_sec": {"type": "integer"}}},
        },
    },
    "get_facts": {
        "type": "function",
        "function": {
            "name": "get_facts",
            "description": "Gather Ansible facts for an allowed host pattern",
            "parameters": {
                "type": "object",
                "properties": {
                    "host_pattern": {"type": "string"},
                    "limit": {"type": "string"},
                    "timeout_sec": {"type": "integer"},
                },
            },
        },
    },
    "run_playbook": {
        "type": "function",
        "function": {
            "name": "run_playbook",
            "description": "Run an Ansible playbook with approval gating",
            "parameters": {
                "type": "object",
                "properties": {
                    "playbook": {"type": "string"},
                    "host_pattern": {"type": "string"},
                    "limit": {"type": "string"},
                    "extra_vars": {"type": "object"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "timeout_sec": {"type": "integer"},
                },
                "required": ["playbook"],
            },
        },
    },
    "check_mode": {
        "type": "function",
        "function": {
            "name": "check_mode",
            "description": "Run an Ansible playbook in check mode (dry-run)",
            "parameters": {
                "type": "object",
                "properties": {
                    "playbook": {"type": "string"},
                    "host_pattern": {"type": "string"},
                    "limit": {"type": "string"},
                    "extra_vars": {"type": "object"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "timeout_sec": {"type": "integer"},
                },
                "required": ["playbook"],
            },
        },
    },
    "get_job_output": {
        "type": "function",
        "function": {
            "name": "get_job_output",
            "description": "Get stored output for a previous Ansible job run",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                },
                "required": ["job_id"],
            },
        },
    },
}


def get_infrastructure_definitions() -> dict[str, dict]:
    """Return OpenAI-compatible tool definitions for infrastructure tools."""
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy({**_SECRETS_AUTOMATION_DEFINITIONS, **INFRASTRUCTURE_DELIVERY_DEFINITIONS})
