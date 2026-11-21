"""LDAP connector helpers."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

from ...services.process_output_redaction import redact_process_output
from ..context import ToolContext
from .common import _string


def _ldap_binary(context: ToolContext) -> str:
    return _string(context.project_config.get("ldapsearch_binary") or "ldapsearch")


def _ldap_server_url(context: ToolContext) -> str:
    return _string(context.project_config.get("ldap_server_url")).rstrip("/")


def _ldap_base_dn(context: ToolContext) -> str:
    return _string(context.project_config.get("ldap_base_dn"))


def _ldap_user_base_dn(context: ToolContext) -> str:
    return _string(context.project_config.get("ldap_user_base_dn") or _ldap_base_dn(context))


def _ldap_group_base_dn(context: ToolContext) -> str:
    return _string(context.project_config.get("ldap_group_base_dn") or _ldap_base_dn(context))


def _ldap_mode(context: ToolContext) -> str:
    return _string(context.project_config.get("ldap_mode") or "ldap").lower()


def _ldap_uid_attribute(context: ToolContext) -> str:
    configured = _string(context.project_config.get("ldap_uid_attribute"))
    return configured or ("sAMAccountName" if _ldap_mode(context) in {"ad", "active_directory"} else "uid")


def _ldap_email_attribute(context: ToolContext) -> str:
    return _string(context.project_config.get("ldap_email_attribute") or "mail")


def _ldap_display_name_attribute(context: ToolContext) -> str:
    configured = _string(context.project_config.get("ldap_display_name_attribute"))
    return configured or ("displayName" if _ldap_mode(context) in {"ad", "active_directory"} else "cn")


def _ldap_group_name_attribute(context: ToolContext) -> str:
    return _string(context.project_config.get("ldap_group_name_attribute") or "cn")


def _ldap_membership_attribute(context: ToolContext) -> str:
    configured = _string(context.project_config.get("ldap_membership_attribute"))
    return configured or ("member" if _ldap_mode(context) in {"ad", "active_directory"} else "memberUid")


def _ldap_user_filter(context: ToolContext) -> str:
    configured = _string(context.project_config.get("ldap_user_filter"))
    return configured or (
        "(objectClass=user)" if _ldap_mode(context) in {"ad", "active_directory"} else "(objectClass=person)"
    )


def _ldap_group_filter(context: ToolContext) -> str:
    return _string(context.project_config.get("ldap_group_filter") or "(objectClass=group)")


def _escape_ldap_filter(value: str) -> str:
    escaped = []
    for char in value:
        escaped.append({"\\": "\\5c", "*": "\\2a", "(": "\\28", ")": "\\29", "\x00": "\\00"}.get(char, char))
    return "".join(escaped)


def _parse_ldif(text: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    last_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip():
            if current:
                entries.append(current)
                current = {}
                last_key = None
            continue
        if line.startswith("#"):
            continue
        if line.startswith(" ") and last_key:
            values = current.get(last_key)
            if isinstance(values, list) and values:
                values[-1] = f"{values[-1]}{line[1:]}"
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        normalized = value.lstrip()
        last_key = key.strip()
        if last_key == "dn":
            current["dn"] = normalized
        else:
            current.setdefault(last_key, []).append(normalized)
    if current:
        entries.append(current)
    return entries


def _ldap_first(entry: dict[str, Any], key: str) -> str:
    value = entry.get(key)
    if isinstance(value, list) and value:
        return str(value[0]).strip()
    if isinstance(value, str):
        return value.strip()
    return ""


def _normalize_ldap_user(entry: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    return {
        "dn": _string(entry.get("dn")),
        "username": _ldap_first(entry, _ldap_uid_attribute(context))
        or _ldap_first(entry, "uid")
        or _ldap_first(entry, "cn"),
        "email": _ldap_first(entry, _ldap_email_attribute(context)),
        "display_name": _ldap_first(entry, _ldap_display_name_attribute(context)) or _ldap_first(entry, "cn"),
        "raw_attributes": {key: value for key, value in entry.items() if key != "dn"},
    }


def _normalize_ldap_group(entry: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    membership_attr = _ldap_membership_attribute(context)
    return {
        "dn": _string(entry.get("dn")),
        "name": _ldap_first(entry, _ldap_group_name_attribute(context)) or _ldap_first(entry, "cn"),
        "members": list(entry.get(membership_attr) or []),
        "raw_attributes": {key: value for key, value in entry.items() if key != "dn"},
    }


async def _ldap_search(
    context: ToolContext, *, base_dn: str, filter_expr: str, attrs: list[str], limit: int = 20, timeout: int = 30
) -> dict[str, Any]:
    binary = _ldap_binary(context)
    if shutil.which(binary) is None and not Path(binary).exists():
        return {"error": f"{binary} is not available on PATH"}
    server_url = _ldap_server_url(context)
    base = _string(base_dn)
    bind_dn = _string(context.project_config.get("ldap_bind_dn"))
    bind_password = _string(context.project_config.get("ldap_bind_password"))
    if not server_url or not base:
        return {"error": "ldap_server_url and ldap_base_dn are required"}
    command = [binary, "-x", "-LLL", "-H", server_url, "-b", base, "-z", str(max(1, limit))]
    if bind_dn:
        command.extend(["-D", bind_dn])
    if bind_password:
        command.extend(["-w", bind_password])
    command.extend([filter_expr, *attrs])
    proc = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        return {"error": f"{binary} search timed out"}
    # The bind password travels as ``-w``; the shown command never carries it.
    shown_command = redact_process_output(
        " ".join("[redacted]" if index and command[index - 1] == "-w" else part for index, part in enumerate(command))
    )
    if proc.returncode != 0:
        # ldapsearch stderr/stdout can carry server URLs, bind DNs and directory data: exit status only.
        return {
            "error": f"ldap_search_failed exit_code={proc.returncode}",
            "error_code": "ldap_search_failed",
            "exit_code": proc.returncode,
            "command": shown_command,
        }
    # The parsed entries are the product; the raw LDIF and stderr are not repeated in the result.
    return {
        "entries": _parse_ldif(stdout.decode("utf-8", errors="replace")),
        "command": shown_command,
        "base_dn": base,
    }


async def _search_ldap_users(
    context: ToolContext, *, query: str = "", limit: int = 20, timeout: int = 30
) -> dict[str, Any]:
    query = _string(query)
    uid_attr = _ldap_uid_attribute(context)
    email_attr = _ldap_email_attribute(context)
    display_attr = _ldap_display_name_attribute(context)
    user_filter = _ldap_user_filter(context)
    if query:
        escaped = _escape_ldap_filter(query)
        search_filter = f"(&{user_filter}(|({uid_attr}=*{escaped}*)({email_attr}=*{escaped}*)({display_attr}=*{escaped}*)(cn=*{escaped}*)))"
    else:
        search_filter = user_filter
    result = await _ldap_search(
        context,
        base_dn=_ldap_user_base_dn(context),
        filter_expr=search_filter,
        attrs=[uid_attr, email_attr, display_attr, "cn", "memberOf"],
        limit=limit,
        timeout=timeout,
    )
    if result.get("error"):
        return result
    users = [_normalize_ldap_user(entry, context) for entry in result["entries"]]
    result["users"] = users
    result["count"] = len(users)
    return result
