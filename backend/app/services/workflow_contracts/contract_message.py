"""The workflow contract message injected at the start of a governed workflow turn.

The texts are prompt catalog keys (``workflow.contract.*``; seeds in
``services/prompt_catalog/seeds/workflow.py``). This module only decides which family branch
applies and fills its placeholders; a workflow-run phase adds its iteration, findings, recorded
inputs and output lines.
"""

from __future__ import annotations

import json
from typing import Any

from ..content_security.untrusted_fence import fenced_untrusted, new_fence, untrusted_notice
from ..prompt_catalog import render_prompt


def _line(key: str, **variables: object) -> str:
    """A contract line fragment: rendered and joined with a leading space."""
    return " " + render_prompt(key, **variables)


def build_workflow_contract_message(workflow_contract: dict[str, Any] | None) -> str:
    message = _family_contract_message(workflow_contract)
    phase = workflow_contract.get("workflow_run_phase") if isinstance(workflow_contract, dict) else None
    if not message or not isinstance(phase, dict):
        return message
    # A phase of a workflow run: its iteration and the findings a loop carried.
    findings = [str(item) for item in phase.get("findings") or [] if str(item or "").strip()]
    lines = [render_prompt(
        "workflow.contract.line.run_phase", phase_title=str(phase.get("title") or "").strip(),
        iteration=str(phase.get("iteration") or 1),
    )]
    # Findings (CI and check output) and recorded artefacts quote external text: untrusted blocks.
    fence = new_fence()
    if findings or (isinstance(phase.get("inputs"), dict) and phase["inputs"]):
        lines.append(untrusted_notice(fence, "the run's gates and artefacts"))
    if findings:
        lines.append(render_prompt("workflow.contract.line.run_findings",
                                   findings=fenced_untrusted("gate findings", "\n".join(findings), fence)))
    if isinstance(phase.get("inputs"), dict) and phase["inputs"]:
        inputs = json.dumps(phase["inputs"], sort_keys=True, default=str)[:6000]
        lines.append(render_prompt("workflow.contract.line.run_inputs",
                                   inputs=fenced_untrusted("recorded artefacts", inputs, fence)))
    output = phase.get("output") if isinstance(phase.get("output"), dict) else None
    if output:
        lines.append(render_prompt("workflow.contract.line.run_output", kind=str(output.get("kind") or "")
                                   .replace("_", " "), tool=str(output.get("tool") or "")))
    return f"{message}\n\n{' '.join(lines)}"


def _family_contract_message(workflow_contract: dict[str, Any] | None) -> str:
    if not isinstance(workflow_contract, dict) or not workflow_contract:
        return ""
    topic = str(workflow_contract.get("topic") or "the requested topic").strip()
    phases = [
        str(phase.get("id") or "").strip()
        for phase in (workflow_contract.get("phases") or [])
        if isinstance(phase, dict)
    ]
    phase_text = ", ".join(item for item in phases if item) or "workflow"
    completion_line = ""
    evidence_contract = workflow_contract.get("evidence_contract")
    if isinstance(evidence_contract, dict) and evidence_contract.get("required_axes"):
        axes = ", ".join(str(item) for item in evidence_contract.get("required_axes") or [])
        completion_line = _line("workflow.contract.line.required_axes", axes=axes)
    workflow_id = str(workflow_contract.get("workflow_id") or "").strip()
    if workflow_id == "coding_change_tdd":
        return render_prompt(
            "workflow.contract.coding_change_tdd", topic=topic, phase_text=phase_text, completion_line=completion_line
        )
    if workflow_id == "knowledge_request":
        query_style = str(workflow_contract.get("knowledge_query_style") or "lookup").strip().lower()
        key = (
            "workflow.contract.knowledge_definition" if query_style == "definition"
            else "workflow.contract.knowledge_lookup"
        )
        return render_prompt(key, topic=topic, phase_text=phase_text, completion_line=completion_line)
    return ""
