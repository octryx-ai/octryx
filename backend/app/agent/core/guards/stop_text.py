"""Stop answers of the agent loop: a fixed protocol prefix plus a catalog reason.

``Agent stopped because `` is a protocol marker, not configurable text: session state
and turn failure detection (``services/session/run_state.py``,
``services/session/turn_failure.py``, ``services/sub_agent_group/evidence.py``) and the
no-tool follow-up guard recognise a stopped run by it. The reason after it is catalog data
(``loop.*_stop`` / ``guard.*_stop`` keys).
"""

from __future__ import annotations

from ....services.prompt_catalog import render_prompt

AGENT_STOP_PREFIX = "Agent stopped because "


def agent_stop_text(key: str, /, **variables: object) -> str:
    return AGENT_STOP_PREFIX + render_prompt(key, **variables)


__all__ = ["AGENT_STOP_PREFIX", "agent_stop_text"]
