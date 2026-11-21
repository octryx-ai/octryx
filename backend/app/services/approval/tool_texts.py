"""Tool calls, risks and approval rules in plain words (see ``presentation`` for where they are shown)."""

from __future__ import annotations

import re
from typing import Any

# Rule codes of ``tool_approval_gate`` (kept as literals: the gate imports this module, not the other way round).
RULE_REQUIRE_FOR_TOOLS = "require_for_tools"
RULE_REQUIRE_FOR_RISKS = "require_for_risks"
RULE_UNATTENDED_EXTERNAL_WRITE = "unattended_external_write"
RULE_DEVICE_EXTERNAL_WRITE = "device_external_write"
RULE_CHAT_CONNECTOR_WRITE = "chat_connector_write"
RULE_CHAT_PLATFORM_WRITE = "chat_platform_write"
RULE_OUTBOUND_MESSAGE = "outbound_message"

ON_SERVER = "the Octryx server"
ON_DEVICE = "a device"
UNKNOWN_SYSTEM = "an external system"

_RISK_TEXTS = {
    "read": "It only reads",
    "write": "It changes data",
    "admin": "It changes platform administration",
    "unknown": "What it changes is not known, so it counts as a change",
}

# Connectors without a named-connection descriptor (``named_connections.descriptors`` has the others' labels).
_SYSTEM_LABELS = {
    "incident_management": "incident management", "linear": "Linear", "outlook": "Outlook",
    "terraform": "Terraform", "helm": "Helm", "argocd": "Argo CD", "vault": "Vault", "ldap": "LDAP",
    "ansible": "Ansible", "statuspage": "Statuspage", "docker_registry": "the Docker registry",
    "ci_pipelines": "CI pipelines", "grafana": "Grafana", "teams": "Teams",
}
# What a connector's comment or change lands on when the tool name does not say ("add_jira_comment").
_DEFAULT_OBJECT = {"jira": "issue", "confluence": "page", "servicenow": "record"}
_NOUNS = {"ticket": "issue"}
_ARTICLE_VERBS = {"create": "Create", "update": "Update", "delete": "Delete", "close": "Close"}

# Built-in tools whose name alone reads badly; ``{place}`` is where the call runs.
_BUILT_IN_TITLES = {
    "run_cli_command": "Run a command on {place}",
    "http_request": "Send a web request",
    "write_workspace_file": "Write a file in the workspace",
    "edit_workspace_file": "Change a file in the workspace",
    "multi_edit_workspace_file": "Change a file in the workspace",
    "apply_patch_workspace": "Change files in the workspace",
    "ask_reporter_via_teams": "Send the reporter a Teams message",
    "start_runtime_process": "Start a process on {place}",
    "cancel_runtime_process": "Stop a process on {place}",
    "run_saved_python_script": "Run a saved Python script on {place}",
}

_APPROVAL_ACTION = re.compile(r"^Approve tool execution for (?P<name>.+)$")


def _words(name: str) -> str:
    return re.sub(r"[_\-]+", " ", str(name or "")).strip()


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def connector_label(connector: str) -> str:
    """``jira`` -> "Jira": the named-connection descriptor's label, else the table above, else the name in words."""
    from ..named_connections.descriptors import descriptor_of

    descriptor = descriptor_of(connector)
    if descriptor is not None:
        return descriptor.label
    return _SYSTEM_LABELS.get(str(connector or ""), _words(connector).title())


def _mcp_parts(tool_name: str) -> tuple[str, str] | None:
    parts = str(tool_name or "").split("__")
    return (parts[1], "__".join(parts[2:])) if len(parts) >= 3 and parts[0] in {"mcp", "rest"} else None


def system_label(tool_name: str) -> str:
    """The system a call writes to, by name ("Jira", the REST API or MCP server), else "an external system"."""
    from ...tools.definitions import get_tool_definition_metadata

    metadata = get_tool_definition_metadata(str(tool_name or "").strip())
    if metadata.connector:
        return connector_label(metadata.connector)
    parts = _mcp_parts(tool_name)
    return _words(parts[0]) if parts else UNKNOWN_SYSTEM


def _connector_title(tool_name: str, connector: str) -> str:
    """"add_jira_comment" -> "Comment on a Jira issue": verb and object from the name, the system from metadata."""
    label = connector_label(connector)
    connector_tokens = set(connector.split("_"))
    tokens = [token for token in tool_name.split("_") if token and token not in connector_tokens]
    if not tokens:
        return f"Use {label}"
    verb, rest = tokens[0], tokens[1:]
    noun = " ".join(_NOUNS.get(token, token) for token in rest)
    if verb == "add" and rest and rest[-1] == "comment":
        target = " ".join(_NOUNS.get(token, token) for token in rest[:-1]) or _DEFAULT_OBJECT.get(connector, "item")
        return f"Comment on {_article(label)} {label} {target}"
    if verb == "transition" and noun:
        return f"Move {_article(label)} {label} {noun} to another status"
    if verb in _ARTICLE_VERBS and 0 < len(rest) <= 2 and not noun.endswith("s"):
        return f"{_ARTICLE_VERBS[verb]} {_article(label)} {label} {noun}"
    return f"{_sentence(' '.join(tokens))} in {label}"


def tool_title(tool_name: str, *, on_device: bool = False, label: str = "") -> str:
    """What the call does, in words: "Run a command on the Octryx server", "Comment on a Jira issue".

    ``label`` is an explicit approval subject's own name (an MCP capability); an unknown tool reads as its name in
    words, never as "Execute tool <name>"."""
    from ...tools.definitions import get_tool_definition_metadata

    name = str(tool_name or "").strip()
    if label and label != name:
        return f"Use {label}"
    if name in _BUILT_IN_TITLES:
        return _BUILT_IN_TITLES[name].format(place=ON_DEVICE if on_device else ON_SERVER)
    metadata = get_tool_definition_metadata(name)
    if metadata.connector:
        return _connector_title(name, metadata.connector)
    parts = _mcp_parts(name)
    if parts:
        system, operation = parts
        return f"{_sentence(_words(operation))} in {_words(system)}"
    if name.startswith("admin_"):
        return f"{_sentence(_words(name[len('admin_'):]))} (platform administration)"
    return _sentence(_words(name)) or "A tool call"


def risk_text(risk: str) -> str:
    code = str(risk or "").strip().lower()
    return _RISK_TEXTS.get(code, "") if code else ""


def rule_text(rule: str, *, risk: str = "", system: str = "") -> str:
    """Why the person is asked, in one sentence (no ": ", see the module docstring)."""
    where = system or UNKNOWN_SYSTEM
    code = str(rule or "").strip()
    if code == RULE_REQUIRE_FOR_TOOLS:
        return "This tool needs approval in this Workspace"
    if code == RULE_REQUIRE_FOR_RISKS:
        kind = {"write": "Writes", "admin": "Administrative actions"}.get(str(risk or "").lower(), "Actions like this")
        return f"{kind} need approval in this Workspace"
    if code == RULE_UNATTENDED_EXTERNAL_WRITE:
        return f"No person started this run; its write to {where} needs your approval"
    if code == RULE_DEVICE_EXTERNAL_WRITE:
        return f"A device asks to write to {where} through Octryx; it runs only after your approval"
    if code == RULE_CHAT_CONNECTOR_WRITE:
        return f"A write to {where} from the chat; confirm exactly this call before it runs"
    if code == RULE_CHAT_PLATFORM_WRITE:
        return "A change in Octryx from the chat; confirm exactly this call before it runs"
    if code == RULE_OUTBOUND_MESSAGE:
        return "A message to a person outside this chat; it is sent only after your approval"
    return "This call needs approval" if code else ""


def gate_texts(tool_name: str, *, rule: str, risk: str, label: str = "",
               on_device: bool = False) -> dict[str, Any]:
    """The readable fields of a tool gate's preview, plus ``rule``/``risk`` as codes next to them.

    ``explanation`` (the stored detail lines) leaves the subtitle out, so the card does not say
    "This tool needs approval in this Workspace" twice, once as the subtitle and once as the first detail."""
    subtitle = rule_text(rule, risk=risk, system=system_label(tool_name))
    return {
        "title": tool_title(tool_name, on_device=on_device, label=label),
        "subtitle": subtitle,
        "explanation": [line for line in (risk_text(risk),) if line],
        "rule": rule,
        "risk": risk,
    }


def readable_title(title: str, tool_name: str, *, on_device: bool = False) -> str:
    """A stored title in words: a missing one reads as the tool's title; any other title (a tool's own preview,
    "Create Jira issue PROJ-1") stays as it is."""
    text = str(title or "").strip()
    if not text:
        name = str(tool_name or "")
        return tool_title(name, on_device=on_device) if name else text
    return text

__all__ = [
    "ON_DEVICE",
    "ON_SERVER",
    "UNKNOWN_SYSTEM",
    "connector_label",
    "gate_texts",
    "readable_title",
    "risk_text",
    "rule_text",
    "system_label",
    "tool_title",
]
