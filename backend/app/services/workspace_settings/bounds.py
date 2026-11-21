"""What a Workspace admin or owner may change without a platform admin: only tighten.

The Workspace settings editors (budget, coding tools, MCP servers, models) write keys a platform admin
also sets. A Workspace admin may use them, but every write is checked against the current state and
the platform values, and anything that loosens is refused with :class:`LooseningRefusedError` (HTTP 403):

- **Budget** — a session or request cap at or below the platform value (``0`` turns a cap off, so it is looser unless
  the platform cap is off too); a per-person daily budget at or below the baseline.
- **Coding tools** — ``requires_governed_routing`` is switched off only by a platform admin; a baseline command & file
  rule or a baseline blocked permission that is in force cannot be removed (stricter-only against the baseline).
- **MCP servers** (Runtime's Workspace allow, ``services/mcp_workspace_allow``) — a server is switched on only by a
  platform admin, except the Workspace's own registrations; switching off is always allowed.
- **Models** — no switch to *all cleared models*, no newly allowed model, no seat or company models in ``/model``
  that were off.
- **Seat settings** (the seat-mode route, one key per call) — the same: no seat or Codex seat allowed, no added seat
  model, no company models in a seat, ``requires_governed_routing`` not switched off.

Platform admins are not bounded.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from app.services.agent_gateway.policy_keys import BASELINE_DAILY_BUDGET_USD, BASELINE_POLICY

CODE = "platform_admin_required"


class LooseningRefusedError(Exception):
    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.code = CODE
        self.path = path
        self.reason = reason


def check_cap(value: float | None, platform: Decimal, path: str) -> None:
    """``None`` inherits the platform value (always allowed); a number must not exceed an active platform cap."""
    if value is None or platform == 0:
        return
    if value == 0 or Decimal(str(value)) > platform:
        raise LooseningRefusedError(path, f"at most the platform value ({platform:f} USD)")


def check_daily_budget(value: float | None, path: str = "per_person_daily_usd") -> None:
    if value is not None and value > BASELINE_DAILY_BUDGET_USD:
        raise LooseningRefusedError(path, f"at most the platform value ({BASELINE_DAILY_BUDGET_USD} USD)")


def _baseline_in_force(baseline: Iterable[Any], current: Iterable[Any]) -> list[Any]:
    current_list = list(current)
    return [item for item in baseline if item in current_list]


def check_coding(current: Mapping[str, Any], new: Mapping[str, Any]) -> None:
    if current.get("requires_governed_routing") is True and new.get("requires_governed_routing") is not True:
        raise LooseningRefusedError("requires_governed_routing", "only a platform admin can switch it off")
    new_rules = list(new.get("tool_rules") or [])
    for rule in _baseline_in_force(BASELINE_POLICY["tool_rules"], current.get("tool_rules") or []):
        if rule not in new_rules:
            raise LooseningRefusedError(
                f"tool_rules.{rule['id']}", "a baseline rule can only be removed by a platform admin"
            )
    current_deny = (current.get("client_permissions") or {}).get("deny") or []
    new_deny = list((new.get("client_permissions") or {}).get("deny") or [])
    for entry in _baseline_in_force(BASELINE_POLICY["client_permissions"]["deny"], current_deny):
        if entry not in new_deny:
            raise LooseningRefusedError(
                "client_deny", f"{entry} is a baseline rule; only a platform admin can remove it"
            )


_CEILING_RANK = {"read_only": 0, "edit": 1, "bypass": 2}


def check_role_modes(current: Mapping[str, Any], new: Mapping[str, Any]) -> None:
    """A Workspace admin may lower what a role's sessions may do; raising it is a platform admin's decision."""
    for role, value in new.items():
        if _CEILING_RANK.get(value, 0) > _CEILING_RANK.get(current.get(role, "read_only"), 0):
            raise LooseningRefusedError(f"role_modes.{role}", "only a platform admin can raise what a role may do")


def check_mcp_allow(*, allowed: bool, own_server: bool) -> None:
    """A Workspace admin switches a server off, or on only when it is the Workspace's own registration."""
    if allowed and not own_server:
        raise LooseningRefusedError("allowed", "only a platform admin can allow a platform MCP server")


def check_models(before: Mapping[str, Any], allowed_before: set[str], contract: Mapping[str, Any]) -> None:
    if before.get("mode") == "selected" and contract.get("mode") == "all_cleared":
        raise LooseningRefusedError("mode", "only a platform admin can allow every cleared model")
    for key in contract.get("selected") or []:
        if key not in allowed_before:
            raise LooseningRefusedError(f"selected.{key}", "only a platform admin can allow another model")
    seat_before = before.get("seat") or {}
    seat = contract.get("seat") or {}
    if seat_before.get("mode") != "allowed" and seat.get("mode") == "allowed":
        raise LooseningRefusedError("seat.mode", "only a platform admin can allow seats")
    if not seat_before.get("company_models_in_seat") and seat.get("company_models_in_seat"):
        raise LooseningRefusedError(
            "seat.company_models_in_seat", "only a platform admin can offer company models in /model"
        )
    added = set(seat.get("subscription_models") or []) - set(seat_before.get("subscription_models") or [])
    if added:
        raise LooseningRefusedError("seat.subscription_models", "only a platform admin can add subscription models")


def check_seat_setting(key: str, before: Any, after: Any) -> None:
    """One seat key written through the seat-mode route (``seat_policy.set_workspace_seat_setting``): the same
    tightening-only rule as the Models editor and Coding tools (allowing a seat, adding a seat model, offering company
    models in a seat, switching off governed routing are a platform admin's)."""
    if key in ("seat_mode", "codex_seat_mode") and before != "allowed" and after == "allowed":
        raise LooseningRefusedError(key, "only a platform admin can allow seats")
    if key == "requires_governed_routing" and before is True and after is not True:
        raise LooseningRefusedError(key, "only a platform admin can switch it off")
    if key == "seat_allows_governed_models" and before is not True and after is True:
        raise LooseningRefusedError(key, "only a platform admin can offer company models in /model")
    if key == "seat_models" and set(after or []) - set(before or []):
        raise LooseningRefusedError(key, "only a platform admin can add subscription models")
    # ``codex_seat_models``: ``None`` is every Codex model, so restricting to a list or removing ids tightens;
    # going back to every model or adding an id loosens.
    if key == "codex_seat_models" and before is not None and (after is None or set(after) - set(before)):
        raise LooseningRefusedError(key, "only a platform admin can allow more Codex models")


__all__ = [
    "CODE",
    "check_seat_setting",
    "LooseningRefusedError",
    "check_cap",
    "check_coding",
    "check_daily_budget",
    "check_mcp_allow",
    "check_models",
]
