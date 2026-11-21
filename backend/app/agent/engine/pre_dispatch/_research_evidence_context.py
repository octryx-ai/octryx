"""Bounded current-research read pairs; no source authority or canonical provenance is created here."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass

from ....services.workflow_runs.records import WorkflowRunError
from ..messages._engine_message_helpers import _estimate_message_tokens
from ._history_invariant_normalization import normalize_pre_dispatch_history


class ResearchEvidenceContextError(WorkflowRunError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__("needs_configuration", f"The current research evidence context is unavailable: {reason}.", 409)


@dataclass(frozen=True)
class ResearchEvidenceContext:
    call_ids: frozenset[str]
    prompt_budget: int
    source_chars: int
    runtime_budgets: tuple[tuple[str, int], ...] = ()


def retain_research_evidence(messages: list[dict], context: ResearchEvidenceContext, *, target_budget: int) -> list[dict]:
    """Preserve complete system/user text and exact successful current read pairs; discard repeated/foreign reads."""
    results = {m.get("tool_call_id"): i for i, m in enumerate(messages) if m.get("role") == "tool"}
    mandatory: dict[int, dict] = {}
    optional: list[dict[int, dict]] = []
    found = set()
    for index, raw in enumerate(messages):
        role = raw.get("role")
        if role in {"system", "user"}:
            mandatory[index] = copy.deepcopy(raw)
        elif role == "assistant" and raw.get("tool_calls"):
            kept, ordinary = [], []
            for call in raw["tool_calls"]:
                ident = call.get("id")
                if ident in context.call_ids:
                    if ident not in results:
                        raise ResearchEvidenceContextError("current_read_pair_missing")
                    kept.append(copy.deepcopy(call))
                    found.add(ident)
                elif dict(call.get("function") or {}).get("name") != "knowledge_read":
                    ordinary.append(copy.deepcopy(call))
            if kept:
                mandatory[index] = {**copy.deepcopy(raw), "tool_calls": kept}
                for call in kept:
                    pos = results[call["id"]]
                    mandatory[pos] = copy.deepcopy(messages[pos])
            elif ordinary:
                group = {index: {**copy.deepcopy(raw), "tool_calls": ordinary}}
                group.update({results[c["id"]]: copy.deepcopy(messages[results[c["id"]]])
                              for c in ordinary if c["id"] in results})
                optional.append(group)
        elif role != "tool":
            optional.append({index: copy.deepcopy(raw)})
    if found != set(context.call_ids):
        raise ResearchEvidenceContextError("current_read_pair_missing")

    def rebuilt(parts):
        return [parts[key] for key in sorted(parts)]

    minimum = _estimate_message_tokens(rebuilt(mandatory))
    if minimum > context.prompt_budget or not any(m.get("role") == "user" for m in mandatory.values()):
        raise ResearchEvidenceContextError("research_evidence_does_not_fit")
    budget = min(context.prompt_budget, max(target_budget, minimum))
    selected = dict(mandatory)
    for group in reversed(optional):
        candidate = {**selected, **group}
        if _estimate_message_tokens(rebuilt(candidate)) <= budget:
            selected = candidate
    final, normalization = normalize_pre_dispatch_history(rebuilt(selected))
    if normalization.requires_normalization or _estimate_message_tokens(final) > context.prompt_budget:
        raise ResearchEvidenceContextError("research_pairing_unavailable")
    return final


def runtime_context_key(runtime: dict) -> str:
    return json.dumps([runtime.get(key) for key in ("provider_id", "model", "target_id")], separators=(",", ":"))


def _protected_snapshot(messages, call_ids):
    snapshot, found = [], set()
    for message in messages:
        if message.get("role") == "assistant":
            calls = [c for c in message.get("tool_calls") or [] if c.get("id") in call_ids]
            if calls:
                snapshot.append({**message, "tool_calls": calls})
        elif message.get("role") == "tool" and message.get("tool_call_id") in call_ids:
            snapshot.append(message)
            found.add(message["tool_call_id"])
    if found != set(call_ids):
        raise ResearchEvidenceContextError("current_read_pair_missing")
    try:
        return json.dumps(snapshot, sort_keys=True, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError):
        raise ResearchEvidenceContextError("research_pairing_unavailable") from None


def research_attempt_guard(context: ResearchEvidenceContext, dispatch_messages: list[dict]):
    """Pin exact sanitized pairs across fallback/retries; never restore raw or dropped evidence."""
    expected = _protected_snapshot(dispatch_messages, context.call_ids)
    budgets = dict(context.runtime_budgets)

    def validate_attempt(runtime: dict, messages: list[dict]) -> None:
        budget = budgets.get(runtime_context_key(runtime))
        if budget is None or budget <= 0:
            raise ResearchEvidenceContextError("research_context_capacity_unavailable")
        if _protected_snapshot(messages, context.call_ids) != expected:
            raise ResearchEvidenceContextError("protected_research_pair_changed")
        if (_estimate_message_tokens(messages) > budget
                or normalize_pre_dispatch_history(messages)[1].requires_normalization):
            raise ResearchEvidenceContextError("research_evidence_does_not_fit")

    return validate_attempt
