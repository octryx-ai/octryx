"""Closed model-owned proposal schemas, with no server provenance or actor parameters."""
import copy

from ...services.workflow_runs.specification.records import SCHEMAS, TOOLS


def get_specification_output_definitions() -> dict[str, dict]:
    return {tool: {"type": "function", "function": {"name": tool,
        "description": f"Submit {kind} in the current workflow phase only. Server-owned lineage is never input.",
        "parameters": copy.deepcopy(SCHEMAS[kind])}} for kind, tool in TOOLS.items()}
