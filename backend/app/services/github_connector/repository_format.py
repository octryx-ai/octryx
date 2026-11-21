"""Pure GitHub REST helpers: owner matching, error translation and repository serialization."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException


def _github_repository_matches_owner(data: dict[str, Any], owner_filter: str) -> bool:
    owner_filter = owner_filter.strip().lower()
    if not owner_filter:
        return True
    owner = data.get("owner")
    owner_login = str(owner.get("login") if isinstance(owner, dict) else "").strip().lower()
    if owner_login:
        return owner_login == owner_filter
    full_name_owner = str(data.get("full_name") or "").split("/", 1)[0].strip().lower()
    return full_name_owner == owner_filter


def _raise_for_github_status(response: httpx.Response, *, operation: str) -> None:
    if response.status_code < 400:
        return
    detail = _github_error_detail(response)
    raise HTTPException(
        status_code=response.status_code,
        detail=f"Could not {operation}: GitHub returned HTTP {response.status_code}. {detail}",
    )


def _github_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        message = str(payload.get("message") or "").strip()
        if message:
            return message[:300]
    text = response.text.strip()
    if text:
        return text[:300]
    return "No additional error detail was returned."


def _serialize_github_repository(data: dict[str, Any], *, fallback_full_name: str = "") -> dict[str, Any]:
    full_name = str(data.get("full_name") or fallback_full_name)
    return {
        "full_name": full_name,
        "name": str(data.get("name") or full_name.split("/")[-1]),
        "private": bool(data.get("private")),
        "default_branch": str(data.get("default_branch") or "main"),
        "html_url": str(data.get("html_url") or ""),
        "clone_url": str(data.get("clone_url") or ""),
    }


__all__ = [
    "_github_error_detail",
    "_github_repository_matches_owner",
    "_raise_for_github_status",
    "_serialize_github_repository",
]
