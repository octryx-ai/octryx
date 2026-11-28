"""The handoff control plane of the agent gateway as the handoff routine and ``resume`` use it (``handoff``): calls
with the user's gateway login, and the upload and download of a work state bundle."""

from __future__ import annotations

from typing import Any

import httpx

from .platform import CONTROL_PLANE_PREFIX, PlatformResult, SessionContext, call_control_plane
from .state import LocalState
from .tokens import GATEWAY_AUDIENCE, TokenUnavailableError, get_access_token

TIMEOUT = 60.0
UPLOAD_TIMEOUT = 300.0


class _Platform:
    def __init__(self, state: LocalState, context: SessionContext, http: httpx.Client) -> None:
        self.state, self.context, self.http = state, context, http

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> PlatformResult:
        return call_control_plane(self.state, self.context, method, f"/handoff{path}", http=self.http,
                                  timeout=TIMEOUT, body=body)

    def _headers(self) -> dict[str, str]:
        token = get_access_token(self.state, GATEWAY_AUDIENCE, http=self.http)
        return {"Authorization": f"Bearer {token}", **self.context.headers()}

    def upload(self, work_item_id: str, data: bytes) -> tuple[str, str]:
        try:
            response = self.http.post(
                f"{self.context.base_url}{CONTROL_PLANE_PREFIX}/handoff/attachments",
                params={"work_item_id": work_item_id}, content=data, headers=self._headers(), timeout=UPLOAD_TIMEOUT,
            )
        except (httpx.HTTPError, TokenUnavailableError):
            return "", "platform_unreachable"
        if response.status_code != 200:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            code = detail.get("code") if isinstance(detail, dict) else None
            return "", str(code or f"upload_refused_{response.status_code}")
        return str(response.json().get("bundle_id") or ""), ""

    def download(self, bundle_id: str) -> tuple[bytes, str]:
        try:
            response = self.http.get(f"{self.context.base_url}{CONTROL_PLANE_PREFIX}/handoff/attachments/{bundle_id}",
                                     headers=self._headers(), timeout=UPLOAD_TIMEOUT)
        except (httpx.HTTPError, TokenUnavailableError):
            return b"", ""
        if response.status_code != 200:
            return b"", ""
        return response.content, response.headers.get("x-octryx-sha256", "")


def _codes(result: PlatformResult) -> str:
    return result.reason or result.state or f"http_{result.status_code}" or result.outcome
