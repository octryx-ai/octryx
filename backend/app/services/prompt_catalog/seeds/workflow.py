"""Seeds of the workflow contract messages, one per workflow branch.

Fixed protocol fragments a parser or validator depends on (the create_diagram XML rule, the plan JSON
field lists) stay code constants and arrive as placeholders. The only code copy of these texts.
"""

from __future__ import annotations

from ..contract import RISK_HIGH, PromptKeySpec

AREA = "workflow"

SPECS: tuple[PromptKeySpec, ...] = (
    PromptKeySpec(
        key="workflow.contract.coding_change_tdd",
        area=AREA,
        title="Contract: code change with TDD",
        seed=(
            "Workflow contract active for code change delivery about {topic}. Phases: "
            "{phase_text}.{completion_line} This run is using a bounded TDD cycle. Start by "
            "capturing the failing or baseline state with `run_test_suite`, then update the implementation with "
            "structured workspace tools until `run_test_suite` reports `all_green=true`. Use repository intelligence "
            "before broad edits, avoid duplicate raw CLI test reruns when `run_test_suite` already contains the "
            "failure details, and finish with a concise completion summary after the green verification run."
        ),
        placeholders=frozenset({"completion_line", "phase_text", "topic"}),
        description="Workflow contract message of coding_change_tdd. {completion_line} is a line key or empty.",
    ),
    PromptKeySpec(
        key="workflow.contract.knowledge_definition",
        area=AREA,
        title="Contract: Knowledge definition answer",
        seed=(
            "Workflow contract active for knowledge lookup about {topic}. Phases: "
            "{phase_text}.{completion_line} Answer as a direct definition first, then add one short "
            "section with supporting evidence items and sources. Prioritize authoritative cited Knowledge sources that "
            "match the exact topic and avoid broad architectural summaries. If evidence is missing, state the gap and "
            "the exact follow-up lookup needed."
        ),
        placeholders=frozenset({"completion_line", "phase_text", "topic"}),
        risk=RISK_HIGH,
        description="Evidence rules of a definition-style Knowledge lookup (A1).",
    ),
    PromptKeySpec(
        key="workflow.contract.knowledge_lookup",
        area=AREA,
        title="Contract: Knowledge lookup",
        seed=(
            "Workflow contract active for knowledge lookup about {topic}. Phases: "
            "{phase_text}.{completion_line} Answer with concise synthesis, explicitly separating what "
            "is known from what is inferred. Prefer knowledge sources and do not invent product details beyond "
            "retrieved evidence."
        ),
        placeholders=frozenset({"completion_line", "phase_text", "topic"}),
        risk=RISK_HIGH,
        description="Evidence rules of a Knowledge lookup (A1).",
    ),
    PromptKeySpec(
        key="workflow.checks.reminder",
        area=AREA,
        title="Workflow checks: reminder before finishing",
        seed=(
            "The selected workflow '{workflow_key}' is not done yet. Not met yet: {failed}. Do the missing work "
            "with your tools, base the answer on the results, then write the complete answer again."
        ),
        placeholders=frozenset({"failed", "workflow_key"}),
        risk=RISK_HIGH,
        description=(
            "The one system reminder when a turn of a workflow ends with a failed blocking check (A6); the code "
            "prepends the reminder marker. {failed} lists the failed checks."
        ),
    ),
)
