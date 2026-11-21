"""The hands-on results as the run keeps them: one entry per scenario (the platform's and the repository's)."""

from __future__ import annotations

from typing import Any

from .scenarios import render_step


def pre_existing(result: dict[str, Any], reported: dict[str, Any]) -> dict[str, Any]:
    """A red regression scenario the device ran again on the run's base commit, red there too (``hands_on_base`` in
    the launcher; Coffee acceptance finding 24): reported, never blocking. Only regression scenarios: a feature
    scenario is red on the base by nature."""
    base = str(reported.get("pre_existing") or "")
    if result["passed"] or result.get("part") != "regression" or not base:
        return result
    return {**result, "passed": True, "pre_existing": f"also red on the base {base[:12]}: not this work's"}


def scenario_result(scenario: dict[str, Any], reported: dict[str, Any]) -> dict[str, Any]:
    steps = [*scenario.get("seed", []), *scenario["steps"]]
    index = reported.get("failed_step")
    step = steps[index] if type(index) is int and 0 <= index < len(steps) else None
    from .invalid import invalid_result

    return invalid_result(pre_existing({"id": scenario["id"], "part": scenario["part"], "title": scenario["title"],
                         "passed": reported.get("passed") is True,
                         **({"failed_step": f"{index + 1}: {render_step(step)}"} if step is not None and not
                            reported.get("passed") else {}),
                         **({"error": str(reported.get("error") or "")[:500]} if reported.get("error") else {}),
                         "screenshots": [str(name)[:120] for name in reported.get("screenshots") or []][:8]},
                        reported), reported)


def repo_result(reported: dict[str, Any], titles: dict[str, str]) -> dict[str, Any]:
    ident = str(reported.get("id"))
    index = reported.get("failed_step")
    result = {"id": ident, "part": "regression", "title": titles.get(ident) or ident.removeprefix("repo:")[:200],
              "passed": reported.get("passed") is True,
              **({"failed_step": f"{int(index) + 1}: {reported.get('failed_op') or ''}".strip()}
                 if type(index) is int and not reported.get("passed") else {}),
              **({"error": str(reported.get("error") or "")[:500]} if reported.get("error") else {}),
              "screenshots": [str(name)[:120] for name in reported.get("screenshots") or []][:8]}
    return pre_existing(result, reported)


__all__ = ["pre_existing", "repo_result", "scenario_result"]
