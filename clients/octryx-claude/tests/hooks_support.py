"""Shared helpers for the test_hooks_* modules."""

from __future__ import annotations

from octryx_claude.platform import PlatformResult

KEY = ("0b6c" + "4a52-3b1e-4c1b-9f55-1d1c1b1a1f10")


def _ok(body: dict) -> PlatformResult:
    return PlatformResult("ok", body=body, status_code=200, state=str(body.get("state") or ""),
                          reason=str(body.get("reason") or ""))


def _decision(output: dict) -> str:
    return output["hookSpecificOutput"]["permissionDecision"]
