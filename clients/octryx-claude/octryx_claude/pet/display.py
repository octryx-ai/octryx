"""What the pet shows and which notifications to send (pure).
Only a new item in ``needs_you``, ``done`` or ``problem`` notifies; never in quiet hours or on the first answer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .model import PetItem, PetState
from .settings import PetSettings

NOTIFYING = frozenset({"needs_you", "done", "problem"})
# Connection states next to the platform's states.
OFFLINE = "offline"
SIGNED_OUT = "signed_out"
LABELS = {"needs_you": "Needs you", "problem": "Problem", "working": "Working", "done": "Done",
          "resting": "All quiet", "unknown": "All quiet", OFFLINE: "Offline, retrying",
          SIGNED_OUT: "Signed out: run octryx-claude login"}
TITLE = "Octryx"
MAX_SEEN = 1000  # then only the current items are remembered (a long-running pet stays small)


@dataclass(frozen=True)
class Display:
    status: str  # a platform state, offline or signed_out: picks the badge
    count: int
    tooltip: str
    header: str
    items: tuple[PetItem, ...] = ()
    panel_url: str = "/chat"


@dataclass(frozen=True)
class Notification:
    title: str
    message: str
    url: str | None


def present(pet: PetState | None, connection: str) -> Display:
    if connection == SIGNED_OUT:
        return Display(SIGNED_OUT, 0, f"{TITLE}: {LABELS[SIGNED_OUT]}", LABELS[SIGNED_OUT])
    if pet is None:
        status = OFFLINE if connection == OFFLINE else "resting"
        return Display(status, 0, f"{TITLE}: {LABELS[status]}", LABELS[status])
    label = LABELS.get(pet.state, LABELS["resting"])
    header = f"{label} ({pet.count})" if pet.count and pet.state != "resting" else label
    if pet.state == "problem" and pet.reason:
        header = f"{header}: {pet.reason.replace('_', ' ')}"
    status = OFFLINE if connection == OFFLINE else pet.state
    if status == OFFLINE:
        header = f"{LABELS[OFFLINE]} (last: {header})"
    tooltip = f"{TITLE}: {header}" + (f"\n{pet.headline}" if pet.headline else "")
    return Display(status, pet.count, tooltip, header, pet.items, pet.panel_url)


@dataclass
class Notifier:

    seen: set[str] = field(default_factory=set)
    started: bool = False

    def after(self, pet: PetState, settings: PetSettings, *, now: datetime,
              paused_until: datetime | None = None) -> list[Notification]:
        current = {item.id for item in pet.items}
        new = [item for item in pet.items if item.id not in self.seen and item.kind != "run"]
        first = not self.started
        self.started = True
        self.seen = current if len(self.seen) > MAX_SEEN else self.seen | current
        if first or pet.state not in NOTIFYING or not new:
            return []
        if not settings.notifications or (paused_until is not None and now < paused_until):
            return []
        if pet.quiet_active or settings.quiet_hours.active(now):
            return []
        label = LABELS[pet.state]
        if len(new) == 1:
            return [Notification(f"{TITLE}: {label}", new[0].title or label, new[0].url)]
        return [Notification(f"{TITLE}: {label}", f"{len(new)} new: {new[0].title}", pet.panel_url)]


__all__ = ["LABELS", "NOTIFYING", "OFFLINE", "SIGNED_OUT", "Display", "Notification", "Notifier", "present"]
