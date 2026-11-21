"""Fixed inputs of the judge-area prompt scenarios and their rendering through the current code.

``tests/prompt_catalog_golden_keys_judge.py`` pins ``SCENARIOS``, the digests of these renders.
"""

from __future__ import annotations

from hashlib import sha256


def judge_outputs() -> dict[str, str]:
    from app.agent.loops.control._loop_tool_planner import _planner_messages
    from app.services.prompt_catalog import render_prompt
    from app.services.security_analyzer.llm_risk import RISK_ANSWER_CONTRACT
    from app.services.tool_planning.prompt import _validation_rules

    return {
        "security": render_prompt(
            "judge.security.risk", answer_contract=RISK_ANSWER_CONTRACT, tool_name="bash", capability="change",
            project_label="demo", command_text="rm -rf /tmp/x",
        ),
        "planner:rules": "\n".join(_validation_rules()),
        "planner:system": _planner_messages({})[0]["content"],
        "review": render_prompt("judge.review.task", review_criteria="Accurate", output_to_review="Out."),
    }


def judge_digests() -> dict[str, str]:
    return {name: sha256(text.encode("utf-8")).hexdigest() for name, text in judge_outputs().items()}
