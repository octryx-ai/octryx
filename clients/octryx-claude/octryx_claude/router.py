"""The routing suggestion of the local decision model."""

from __future__ import annotations

import math
import time
from typing import Any

from .local_model import LocalModel

MAX_PROMPT_CHARS = 4000
TIERS = {
    "trivial": "tiny edit, writing a short file, renaming, a simple question about one thing",
    "normal": "ordinary coding task: fix one bug or test, explain code, small feature in one area",
    "hard": "multi-file refactor, architecture or migration plan, debugging a failing system, security review",
}
SUGGESTION = {"trivial": ("claude-haiku-5-5", "low"), "normal": ("claude-sonnet-5-5", "medium"),
              "hard": ("claude-opus-5-5", "high")}


def route_request(prompt: str) -> dict[str, Any]:
    return {"state": f"Request to a coding assistant: {prompt.strip()[:MAX_PROMPT_CHARS]}",
            "questions": {"tier": {"type": "choice", "instructions": "How demanding is this request for the coding "
                                   "assistant?", "criteria": TIERS}}}


def read_route(answer: dict[str, Any]) -> dict[str, Any] | None:
    tier = ((answer or {}).get("answers") or {}).get("tier") or {}
    choice = tier.get("choice")
    if choice not in TIERS:
        return None
    probabilities = {key: round(float(value), 3) for key, value in (tier.get("probabilities") or {}).items()
                     if key in TIERS}
    model, effort = SUGGESTION[choice]
    return {"tier": choice, "confidence": round(float(tier.get("confidence") or 0), 3),
            "probabilities": probabilities, "suggested_model": model, "suggested_effort": effort}


SYSTEM_PROMPT = (
    "You rate how demanding a request to a coding assistant is. Tiers:\n"
    + "".join(f"- {tier}: {text}\n" for tier, text in TIERS.items())
    + "Examples:\n"
    "- 'Rename foo() to load() in api.py' -> trivial\n"
    "- 'What does HTTP 404 mean?' -> trivial\n"
    "- 'Fix the off-by-one error in pagination' -> normal\n"
    "- 'Add a CSV export button to the report page' -> normal\n"
    "- 'Users get logged out randomly in production, investigate' -> hard\n"
    "- 'Move auth from sessions to JWT across all services' -> hard\n"
    "Answer with exactly one word: trivial, normal or hard."
)


def chat_request(prompt: str) -> dict[str, Any]:
    return {"messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": prompt.strip()[:MAX_PROMPT_CHARS]}],
            "max_tokens": 1, "temperature": 0, "logprobs": True, "top_logprobs": 20,
            "chat_template_kwargs": {"enable_thinking": False}}


def _tier_of(token: str) -> str | None:
    word = str(token or "").strip().lower()
    if not word:
        return None
    return next((tier for tier in TIERS if tier.startswith(word) or word.startswith(tier)), None)


def read_chat_route(answer: dict[str, Any]) -> dict[str, Any] | None:
    try:
        first = answer["choices"][0]["logprobs"]["content"][0]
        candidates = first.get("top_logprobs") or [first]
    except (KeyError, IndexError, TypeError):
        return None
    mass = dict.fromkeys(TIERS, 0.0)
    for candidate in candidates:
        tier = _tier_of(candidate.get("token"))
        logprob = candidate.get("logprob")
        if tier is not None and isinstance(logprob, int | float):
            mass[tier] += math.exp(float(logprob))
    total = sum(mass.values())
    if total <= 0:
        return None
    probabilities = {tier: round(value / total, 3) for tier, value in mass.items()}
    choice = max(probabilities, key=probabilities.get)
    model, effort = SUGGESTION[choice]
    return {"tier": choice, "confidence": probabilities[choice], "probabilities": probabilities,
            "suggested_model": model, "suggested_effort": effort}


async def suggest(model: LocalModel, prompt: str) -> dict[str, Any] | None:
    if not (prompt or "").strip():
        return None
    started = time.monotonic()
    try:
        if model.spec.protocol == "chat":
            route = read_chat_route(await model.ask("/v1/chat/completions", chat_request(prompt)))
        else:
            route = read_route(await model.ask("/v1/systemone", route_request(prompt)))
    except Exception:  # noqa: BLE001 - the suggestion is optional; the turn never waits for or fails on it
        return None
    if route is not None:
        route["ms"] = int((time.monotonic() - started) * 1000)
    return route


__all__ = ["SUGGESTION", "SYSTEM_PROMPT", "TIERS", "chat_request", "read_chat_route", "read_route", "route_request",
           "suggest"]
