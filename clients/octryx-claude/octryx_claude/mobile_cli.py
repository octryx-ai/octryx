"""``octryx-claude mobile pair``: connect a phone to Octryx Mobile with a QR code."""

from __future__ import annotations

import argparse
import sys
import time
import webbrowser
from collections.abc import Callable
from typing import Any

import httpx

from . import qr
from .state import LocalState
from .tokens import GATEWAY_AUDIENCE, TokenUnavailableError, get_access_token

PATH = "/api/v1/agent-gateway/mobile/pairings"
TIMEOUT = 10.0
POLL_SECONDS = 1.5
WAIT_LIMIT_SECONDS = 6 * 60


def add_parser(sub: argparse._SubParsersAction) -> None:
    mobile = sub.add_parser("mobile", help="Octryx Mobile: control your sessions from your phone")
    actions = mobile.add_subparsers(dest="mobile_command", required=True)
    actions.add_parser("pair", help="connect a phone with a QR code (you confirm the connection here)")


def platform_url(state: LocalState) -> str:
    return str(state.credentials().get("base_url") or state.config().get("base_url") or "").rstrip("/")


class _Platform:
    def __init__(self, state: LocalState, http: httpx.Client) -> None:
        self.state = state
        self.http = http
        self.base_url = platform_url(state)

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        token = get_access_token(self.state, GATEWAY_AUDIENCE, http=self.http)
        try:
            response = self.http.request(method, f"{self.base_url}{path}", json=body, timeout=TIMEOUT,
                                         headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError:
            return 0, {"reason": "platform_unreachable"}
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return response.status_code, payload if isinstance(payload, dict) else {}


def _say(text: str) -> None:
    print(text, flush=True)


def _reason(payload: dict[str, Any]) -> str:
    reason = str(payload.get("reason") or "")
    return reason if reason.replace("_", "").isalnum() and len(reason) <= 64 else "refused"


def run_pair(state: LocalState, *, http: httpx.Client | None = None,
             open_browser: Callable[[str], object] = webbrowser.open,
             interactive: bool | None = None, sleep: Callable[[float], None] = time.sleep,
             clock: Callable[[], float] = time.monotonic) -> int:
    if not (sys.stdout.isatty() if interactive is None else interactive):
        sys.stderr.write("octryx-claude: mobile pair needs a terminal (it shows the QR code)\n")
        return 2
    if not platform_url(state):
        sys.stderr.write("octryx-claude: not configured; run: octryx-claude login --base-url <platform>\n")
        return 2
    client = http or httpx.Client()
    try:
        platform = _Platform(state, client)
        try:
            status, created = platform.call("POST", PATH)
        except TokenUnavailableError as exc:
            sys.stderr.write(f"octryx-claude: not logged in ({exc.code}); run: octryx-claude login\n")
            return 2
        if status != 201 or not isinstance(created.get("url"), str):
            reason = _reason(created)
            relogin = reason in ("mobile_pairing_scope_missing", "device_login_required",
                                 "mobile_pairing_login_required")
            hint = "; run octryx-claude login" if relogin else ""
            sys.stderr.write(f"octryx-claude: the platform refused the pairing ({reason}){hint}\n")
            return 2 if status == 0 else 1
        confirm_url = str(created.get("confirm_url") or "")
        if (not created["url"].startswith(f"{platform.base_url}/m/pair#c=")
                or not confirm_url.startswith(f"{platform.base_url}/m/confirm?p=")):
            sys.stderr.write("octryx-claude: the platform answered an unexpected pairing address; nothing is shown\n")
            return 1
        pairing_id = str(created.get("pairing_id") or "")
        _say("Scan this with your iPhone camera (it opens Safari; the VPN must be on). Valid for two minutes.\n")
        for line in qr.terminal_lines(qr.encode(created["url"])):
            _say(line)
        _say("")
        view = _wait(platform, pairing_id, until={"scanned", "expired", "denied", "claimed"}, sleep=sleep, clock=clock)
        if view.get("state") != "scanned":
            _say(f"No phone connected ({view.get('state') or _reason(view)}). Run octryx-claude mobile pair again.")
            return 1
        phone, number = str(view.get("phone") or "A phone"), str(view.get("match_number") or "??")
        # The confirmation belongs to the person's signed-in browser, never to this login's token.
        _say(f"{phone} shows the number {number}. Confirm it in your browser, where you are signed in to the platform:")
        _say(f"  {confirm_url}")
        try:
            open_browser(confirm_url)
        except Exception:  # noqa: BLE001 - the address is printed; opening it is a convenience
            pass
        view = _wait(platform, pairing_id, until={"confirmed", "claimed", "denied", "expired"}, sleep=sleep,
                     clock=clock)
        if view.get("state") not in ("confirmed", "claimed"):
            _say(f"Not connected ({view.get('state') or _reason(view)}).")
            return 1
        _say("Confirmed. On the iPhone: Share → \"Add to Home Screen\", then open Octryx from the Home Screen.")
        _say("You see and revoke your phones in the platform under My settings → Devices.")
        return 0
    finally:
        if http is None:
            client.close()


def _wait(platform: _Platform, pairing_id: str, *, until: set[str], sleep: Callable[[float], None],
          clock: Callable[[], float]) -> dict[str, Any]:
    deadline = clock() + WAIT_LIMIT_SECONDS
    while clock() < deadline:
        status, view = platform.call("GET", f"{PATH}/{pairing_id}")
        if status != 200:
            return view
        if view.get("state") in until:
            return view
        sleep(POLL_SECONDS)
    return {"state": "expired"}


def run_mobile_command(args: argparse.Namespace, state: LocalState) -> int:
    return run_pair(state)


__all__ = ["add_parser", "run_mobile_command", "run_pair"]
