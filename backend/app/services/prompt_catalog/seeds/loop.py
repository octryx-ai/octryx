"""Seeds of the agent loop's response guards: reminders, nudges and stop texts."""

from __future__ import annotations

from ..contract import RISK_HIGH, PromptKeySpec

AREA = "loop"

SPECS: tuple[PromptKeySpec, ...] = (
    PromptKeySpec(
        key="loop.followup.instruction.knowledge_request",
        area=AREA,
        title="Unsatisfied contract: Knowledge request (citations)",
        seed=(
            "Do not answer yet. Retrieve the required evidence first with knowledge_search, then answer grounded "
            "strictly in what you found, citing each source as a link to its source_url. Do not build or promise a "
            "deliverable (deck, document) that was not requested."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="loop.followup.instruction.other",
        area=AREA,
        title="Unsatisfied contract: other evidence workflows",
        seed=(
            "Do not answer yet. Retrieve the required evidence first with the available knowledge tools (e.g. "
            "knowledge_search / knowledge_read), then answer grounded strictly in what you found. Do not build or "
            "promise a deliverable (deck, document) that was not requested."
        ),
        risk=RISK_HIGH,
    ),
)
