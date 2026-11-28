"""Every attention action carries the exact request that answers it (the UI knows no decision endpoints)."""

from __future__ import annotations

from typing import Any

TONES = ("primary", "neutral", "danger")


def action(key: str, label: str, *, method: str = "POST", path: str, body: dict[str, Any] | None = None,
           tone: str = "neutral", input_: dict[str, Any] | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"key": key, "label": label, "tone": tone if tone in TONES else "neutral",
                            "request": {"method": method, "path": path, "body": dict(body or {})}}
    if input_ is not None:
        item["input"] = input_
    return item


def text_input(field: str, label: str, *, required: bool = True, placeholder: str = "") -> dict[str, Any]:
    return {"kind": "text", "field": field, "label": label, "placeholder": placeholder, "required": required}


def run_actions(run_id: str, offered: list[dict[str, Any]], *, payload_hash: str | None) -> list[dict[str, Any]]:
    path = f"/api/v1/workflow-runs/{run_id}/actions"
    actions = []
    for offer in offered:
        key = str(offer.get("key") or "")
        if not key or key in ("change_runtime", "resume_in_new_session", "take_over"):
            continue
        body: dict[str, Any] = {"action": key}
        if offer.get("payload_hash") or (payload_hash and key in ("confirm", "change", "stop", "reply")):
            body["payload_hash"] = offer.get("payload_hash") or payload_hash
        if key == "continue":
            body["k"] = 1
        raw = offer.get("input") if isinstance(offer.get("input"), dict) else None
        input_ = None
        if raw is not None and raw.get("kind") == "text":
            input_ = text_input(str(raw.get("name") or "reason"), str(raw.get("label") or "Your answer"),
                                required=bool(raw.get("required")))
        elif raw is not None:
            continue  # a structured input (e.g. a runtime choice) belongs to the run card
        tone = str(offer.get("tone") or ("primary" if key in ("confirm", "approve", "continue", "reply",
                                                                "approve_tool") else "neutral"))
        actions.append(action(key, str(offer.get("label") or key), path=path, body=body, tone=tone, input_=input_))
    return actions


__all__ = ["action", "run_actions", "text_input"]
