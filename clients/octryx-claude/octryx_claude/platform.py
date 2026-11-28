"""Calls from the hooks and the launcher to the Octryx client control plane; a call never raises."""

from __future__ import annotations

import os
import re
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from .state import LocalState
from .tokens import GATEWAY_AUDIENCE, TokenUnavailableError, get_access_token

CONTROL_PLANE_PREFIX = "/api/v1/agent-gateway"
HEADER_SESSION = "X-Octryx-Session"
HEADER_WORKSPACE = "X-Octryx-Workspace"
HEADER_WORK_ITEM = "X-Octryx-Work-Item"
# The workflow run a device job works on; the platform checks it before binding the session to the run.
HEADER_WORKFLOW_RUN = "X-Octryx-Workflow-Run"
HEADER_STATE = "x-octryx-gateway-state"
HEADER_REASON = "x-octryx-gateway-reason"

# Environment the launcher hands to Claude Code; hooks inherit it.
ENV_SESSION_KEY = "OCTRYX_SESSION_KEY"
ENV_WORKSPACE_ID = "OCTRYX_WORKSPACE_ID"
ENV_WORK_ITEM = "OCTRYX_WORK_ITEM"
ENV_WORKFLOW_RUN = "OCTRYX_WORKFLOW_RUN"
ENV_BASE_URL = "OCTRYX_BASE_URL"
ENV_PROFILE = "OCTRYX_PROFILE"  # governed | seat

_CODE = re.compile(r"^[a-z0-9_]{1,64}$")
# Header-safe identifiers: Workspace ids are UUIDs, work items are tracker keys.
_HEADER_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$")


def safe_code(value: object) -> str:
    text = str(value or "")
    return text if _CODE.match(text) else ""


def valid_header_value(value: str) -> bool:
    return bool(_HEADER_VALUE.match(value or ""))


@dataclass(frozen=True)
class SessionContext:
    base_url: str
    session_key: str
    workspace_id: str
    work_item: str = ""
    # A device job's run: sent with every control-plane call, so registration binds the session to it.
    workflow_run: str = ""

    def headers(self) -> dict[str, str]:
        headers = {HEADER_SESSION: self.session_key, HEADER_WORKSPACE: self.workspace_id}
        if self.work_item:
            headers[HEADER_WORK_ITEM] = self.work_item
        if self.workflow_run:
            headers[HEADER_WORKFLOW_RUN] = self.workflow_run
        return headers

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> SessionContext | None:
        source = os.environ if env is None else env
        base_url = str(source.get(ENV_BASE_URL) or "").rstrip("/")
        session_key = str(source.get(ENV_SESSION_KEY) or "")
        workspace_id = str(source.get(ENV_WORKSPACE_ID) or "")
        work_item = str(source.get(ENV_WORK_ITEM) or "")
        workflow_run = str(source.get(ENV_WORKFLOW_RUN) or "")
        try:
            session_key = str(uuid.UUID(session_key))
        except ValueError:
            return None
        if not base_url or not valid_header_value(workspace_id):
            return None
        if work_item and not valid_header_value(work_item):
            return None
        return cls(base_url, session_key, workspace_id, work_item,
                   workflow_run if valid_header_value(workflow_run) else "")


@dataclass(frozen=True)
class PlatformResult:
    outcome: str  # ok | refused | unreachable
    body: dict[str, Any] = field(default_factory=dict)
    status_code: int = 0
    state: str = ""
    reason: str = ""


#: The pause before the one retry of a hook call that did not reach the platform.
RETRY_DELAY_SECONDS = 2.0
#: Answers of a proxy in front of the platform (no gateway state header): the platform never saw the call.
_PROXY_STATUSES = frozenset({502, 503, 504})


def _transient(result: PlatformResult) -> bool:
    # Only a call that never reached the platform is safe to repeat: the platform has not acted on it.
    if result.outcome == "unreachable":
        return result.reason == "platform_connect_failed"
    return result.outcome == "refused" and result.status_code in _PROXY_STATUSES and not result.state


def call_control_plane(
    state: LocalState,
    context: SessionContext,
    method: str,
    path: str,
    *,
    http: httpx.Client,
    timeout: float,
    body: dict[str, Any] | None = None,
    retry: bool = False,
) -> PlatformResult:
    # A platform deploy is briefly unreachable; without the retry the PreToolUse hook would deny and pause the run.
    result = _call_once(state, context, method, path, http=http, timeout=timeout, body=body)
    if retry and _transient(result):
        time.sleep(RETRY_DELAY_SECONDS)
        result = _call_once(state, context, method, path, http=http, timeout=timeout, body=body)
    if result.reason == "platform_connect_failed":
        return PlatformResult("unreachable", reason="platform_unreachable")
    return result


def _call_once(
    state: LocalState,
    context: SessionContext,
    method: str,
    path: str,
    *,
    http: httpx.Client,
    timeout: float,
    body: dict[str, Any] | None = None,
) -> PlatformResult:
    try:
        token = get_access_token(state, GATEWAY_AUDIENCE, http=http)
    except TokenUnavailableError as exc:
        return PlatformResult("unreachable", reason=exc.code)
    headers = {"Authorization": f"Bearer {token}", **context.headers()}
    url = f"{context.base_url}{CONTROL_PLANE_PREFIX}{path}"
    try:
        response = http.request(method, url, headers=headers, json=body, timeout=timeout)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return PlatformResult("unreachable", reason="platform_connect_failed")  # the request never left
    except httpx.HTTPError:
        return PlatformResult("unreachable", reason="platform_unreachable")
    if response.status_code != 200:
        return PlatformResult(
            "refused",
            status_code=response.status_code,
            state=safe_code(response.headers.get(HEADER_STATE)),
            reason=safe_code(response.headers.get(HEADER_REASON)),
        )
    try:
        payload = response.json()
    except ValueError:
        return PlatformResult("refused", status_code=200, reason="invalid_response")
    if not isinstance(payload, dict):
        return PlatformResult("refused", status_code=200, reason="invalid_response")
    return PlatformResult(
        "ok",
        body=payload,
        status_code=200,
        state=safe_code(payload.get("state")),
        reason=safe_code(payload.get("reason")),
    )
