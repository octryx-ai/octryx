"""The pet's poll loop, apart from any tray toolkit (``tray`` drives it; the tests use a fake view).

Each round: read the settings (so ``octryx-claude pet quiet`` applies without a restart), fetch with the last ETag,
keep the last state on 304, show it, send the notifications :class:`display.Notifier` answers, and wait for the
schedule's delay or a wake-up from the menu ("Refresh now", a settings change).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

import httpx

from . import api
from . import settings as pet_settings
from .account import Account
from .display import OFFLINE, SIGNED_OUT, Display, Notification, Notifier, present
from .model import PetState
from .schedule import Schedule

logger = logging.getLogger("octryx_claude.pet")


class View(Protocol):
    def show(self, display: Display) -> None: ...

    def notify(self, notification: Notification) -> None: ...


class Runner:
    def __init__(self, account: Account, view: View, *, http: httpx.Client | None = None,
                 fetch: Callable[..., api.FetchResult] = api.fetch, schedule: Schedule | None = None,
                 now: Callable[[], datetime] = datetime.now, project_id: str = "") -> None:
        self.account = account
        self.view = view
        self.http = http or httpx.Client()
        self._fetch = fetch
        self.schedule = schedule or Schedule()
        self.notifier = Notifier()
        self.now = now
        self.project_id = project_id
        self.pet: PetState | None = None
        self.etag = ""
        self.connection = "ok"
        self.paused_until: datetime | None = None
        self._wake = threading.Event()
        self._stop = threading.Event()

    # --- one round ------------------------------------------------------------------------------------------

    def tick(self) -> float:
        """Fetch once, show, notify; answers the seconds until the next round."""
        current = pet_settings.load(self.account.root)
        result = self._fetch(self.account, http=self.http, etag=self.etag, project_id=self.project_id)
        if result.outcome == "ok" and result.pet is not None:
            self.pet, self.etag, self.connection = result.pet, result.etag, "ok"
            for notification in self.notifier.after(result.pet, current, now=self.now(),
                                                    paused_until=self.paused_until):
                self._notify(notification)
            delay = self.schedule.after_answer(result.pet.state, result.pet.poll_after_seconds)
        elif result.outcome == "not_modified" and self.pet is not None:
            self.connection = "ok"
            delay = self.schedule.after_answer(self.pet.state, self.pet.poll_after_seconds)
        elif result.outcome == "signed_out":
            self.pet, self.etag, self.connection = None, "", SIGNED_OUT
            delay = self.schedule.after_signed_out()
        elif result.outcome == "refused":
            logger.warning("pet state refused: %s %s", result.status_code, result.reason)
            self.etag, self.connection = "", SIGNED_OUT if result.status_code in (401, 403) else OFFLINE
            delay = self.schedule.after_signed_out() if result.status_code == 403 else self.schedule.after_failure()
        else:  # unreachable, or a 304 without a state to keep
            self.etag, self.connection = "", OFFLINE
            delay = self.schedule.after_failure()
        self.view.show(self.display())
        return delay

    def display(self) -> Display:
        return present(self.pet, self.connection)

    def _notify(self, notification: Notification) -> None:
        url = api.resolve(self.account.base_url(), notification.url)
        try:
            self.view.notify(Notification(notification.title, notification.message, url))
        except Exception:  # noqa: BLE001 - a failed notification never stops the pet
            logger.warning("notification failed", exc_info=True)

    # --- loop and menu actions ------------------------------------------------------------------------------

    def loop(self) -> None:
        while not self._stop.is_set():
            try:
                delay = self.tick()
            except Exception:  # noqa: BLE001 - the pet keeps running; the next round retries
                logger.exception("pet round failed")
                self.connection = OFFLINE
                delay = self.schedule.after_failure()
            self._wake.wait(delay)
            self._wake.clear()

    def refresh_now(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def pause(self, hours: float) -> None:
        self.paused_until = self.now() + timedelta(hours=hours) if hours > 0 else None

    def paused(self) -> bool:
        return self.paused_until is not None and self.now() < self.paused_until

    def quiet_hours(self) -> pet_settings.QuietHours:
        return pet_settings.load(self.account.root).quiet_hours

    def toggle_quiet_hours(self) -> None:
        current = pet_settings.load(self.account.root)
        pet_settings.save(self.account.root, pet_settings.with_quiet_hours(
            current, enabled=not current.quiet_hours.enabled))

    def link(self, url: str | None) -> str | None:
        return api.resolve(self.account.base_url(), url)


__all__ = ["Runner", "View"]
