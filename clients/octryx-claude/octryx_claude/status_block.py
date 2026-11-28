"""The status block: is seat and governance set up, and what does this session use.
Printed on stderr at every start and by ``octryx-claude status``; numbers, fixed codes and labels only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TextIO

from . import model_picker, profile_choice, seat_status, usage
from .platform import PlatformResult, valid_header_value
from .profile_choice import ProfileChoice
from .seat_status import SeatState
from .state import LocalState

PREFIX = "octryx-claude: "
SEAT_LABEL = "seat (your Claude subscription):"
GOVERNED_LABEL = "governed (company model):"
ALLOWANCE_LABEL = "seat allowance:"
BUDGET_LABEL = "daily budget:"
PICKER_LABEL = "company models (/model):"
GOVERNED_READY = "ready"
GOVERNED_NO_MODEL = ("needs_configuration: no Claude model admitted and seat not allowed (an admin adds a Claude "
                     "model to the Workspace, an Anthropic key or Bedrock with Claude, or allows Claude Code seats "
                     "in the Workspace's model settings)")
GOVERNED_NO_COMPANY_MODEL = ("no company model admitted for this Workspace (an admin adds a model and its key in the "
                             "Workspace's model settings)")
NO_MODEL_AVAILABLE = (f"no model available: log in with your Claude subscription (`{seat_status.SEAT_LOGIN_COMMAND}`) "
                      "or have an admin add a model key to the Workspace")
_WIDTH = max(len(SEAT_LABEL), len(GOVERNED_LABEL))


def governed_label(policy_ok: bool, codes: str, *, unusable: bool = False, no_company_model: bool = False) -> str:
    if not policy_ok:
        return f"not set up (client policy {codes})"
    if unusable:
        return GOVERNED_NO_MODEL
    # Outsider walk: "governed: ready" next to "company models: none admitted" read as a contradiction.
    return GOVERNED_NO_COMPANY_MODEL if no_company_model else GOVERNED_READY


def no_company_model(policy: Mapping[str, object]) -> bool:
    if not isinstance(policy, Mapping):
        return True
    return not [row for row in model_picker.picker_rows(policy, profile_choice.PROFILE_GOVERNED)
                if row["source"] == model_picker.SOURCE_COMPANY]


def model_note(policy: Mapping[str, object], seat: SeatState) -> str:
    usable_seat = seat.code in (seat_status.STATE_READY, seat_status.STATE_LIMIT_REACHED)
    return NO_MODEL_AVAILABLE if no_company_model(policy) and not usable_seat else ""


def nothing_to_run_on(policy: Mapping[str, object], seat: SeatState) -> bool:
    return seat.code == seat_status.STATE_FORBIDDEN and no_company_model(policy)


def session_model(claude_args: Sequence[str], aliases: Mapping[str, str]) -> str:
    model = ""
    for index, arg in enumerate(claude_args):
        if arg == "--model" and index + 1 < len(claude_args):
            model = claude_args[index + 1]
        elif arg.startswith("--model="):
            model = arg.split("=", 1)[1]
    if model and valid_header_value(model):
        return f"{model} (from --model)"
    return str(aliases.get("main") or "")


def admitted_note(policy: Mapping[str, Any], profile: str, model: str) -> str:
    if profile != profile_choice.PROFILE_GOVERNED:
        return model
    company = [row["model"] for row in model_picker.picker_rows(policy, profile)
               if row["source"] == model_picker.SOURCE_COMPANY]
    bare = model.split(" (from --model)", 1)[0]
    if not company or bare in company or f"company/{bare}" in company or bare.removeprefix("company/") in company:
        return model
    return f"{model} — not admitted here; choose one of the company models with /model"


def render(*, workspace_label: str, seat: SeatState, governed: str, choice: ProfileChoice | None = None,
           model: str = "", upcoming: bool = False, usage_result: PlatformResult | None = None,
           company_models: str = "") -> list[str]:
    lines = [
        f"Workspace {workspace_label}",
        f"  {SEAT_LABEL:<{_WIDTH}} {seat.label}",
        f"  {GOVERNED_LABEL:<{_WIDTH}} {governed}",
    ]
    if usage_result is not None:
        if seat.code not in (seat_status.STATE_FORBIDDEN, seat_status.STATE_UNKNOWN):
            lines.append(f"  {ALLOWANCE_LABEL:<{_WIDTH}} {usage.allowance_label(usage_result)}")
        lines.append(f"  {BUDGET_LABEL:<{_WIDTH}} {usage.budget_label(usage_result)}")
    if choice is not None:
        which = "next session" if upcoming else "this session"
        lines.append(f"  → {which}: {choice.profile}, model {model} ({choice.reason})")
    if company_models:
        lines.append(f"  {PICKER_LABEL:<{_WIDTH}} {company_models}")
    if seat.code not in (seat_status.STATE_FORBIDDEN, seat_status.STATE_UNKNOWN):
        lines.append(f"  seat login: {seat_status.SEAT_LOGIN_COMMAND}")
    return [f"{PREFIX}{line}" for line in lines]


def policy_ok(result: PlatformResult) -> bool:
    return result.outcome == "ok" and result.state == "allowed"


def seat_state_for(state: LocalState, result: PlatformResult) -> SeatState:
    ok = policy_ok(result)
    return seat_status.seat_state(state, policy_ok=ok, seat_refusal=seat_status.seat_refusal(result.body) if ok else "",
                                  logged_in=profile_choice.seat_logged_in(state))


def lines_for(state: LocalState, result: PlatformResult, codes: str, *, workspace: str, requested: str,
              model: str = "", seat: SeatState | None = None, upcoming: bool = False,
              usage_result: PlatformResult | None = None) -> list[str]:
    ok = policy_ok(result)
    seat = seat or seat_state_for(state, result)
    choice = profile_choice.choose_profile(requested, seat=seat) if ok else None
    company_models = model_picker.status_label(result.body, choice.profile) if choice is not None else ""
    if choice is not None and model:
        model = admitted_note(result.body, choice.profile, model)
    unusable = ok and nothing_to_run_on(result.body, seat)
    lines = render(workspace_label=workspace, seat=seat,
                   governed=governed_label(ok, codes, unusable=unusable,
                                           no_company_model=ok and no_company_model(result.body)),
                   choice=choice, model=model, upcoming=upcoming, usage_result=usage_result if ok else None,
                   company_models=company_models)
    note = model_note(result.body, seat) if ok and not unusable else ""
    return [*lines, f"{PREFIX}  {note}"] if note else lines


def write(out: TextIO, lines: Sequence[str]) -> None:
    out.write("".join(f"{line}\n" for line in lines))
    out.flush()


__all__ = [
    "admitted_note", "governed_label", "lines_for", "model_note", "no_company_model", "nothing_to_run_on", "policy_ok",
    "render", "seat_state_for",
    "session_model",
    "write",
]
