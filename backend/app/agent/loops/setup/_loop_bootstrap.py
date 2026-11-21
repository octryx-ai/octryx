"""Bootstrap helpers for the standard agent loop."""

from __future__ import annotations


def apply_loop_bootstrap_messages(
    *,
    messages: list[dict[str, str]],
    agent_definition,
    injected_workflow_agent: bool,
    request_analysis: dict[str, object],
    workflow_contract,
    build_request_analysis_contract_message,
    build_workflow_contract_message,
) -> list[dict[str, str]]:
    if injected_workflow_agent:
        injected_prompt = str((agent_definition or {}).get("prompt") or "").strip()
        if injected_prompt and not any(
            item.get("role") == "system" and item.get("content") == injected_prompt
            for item in messages
            if isinstance(item, dict)
        ):
            if messages and messages[-1].get("role") == "user":
                messages.insert(len(messages) - 1, {"role": "system", "content": injected_prompt})
            else:
                messages.append({"role": "system", "content": injected_prompt})

    if messages:  # a selected workflow's message always, the execution contract on explicit needs only
        contract_messages = [
            build_request_analysis_contract_message(request_analysis) if request_analysis.get("analysis_first") else "",
            build_workflow_contract_message(workflow_contract) if (workflow_contract or {}).get("workflow_id") else "",
        ]
        for contract_content in [item for item in contract_messages if str(item or "").strip()]:
            contract_message = {"role": "system", "content": contract_content}
            if any(
                item.get("role") == "system" and item.get("content") == contract_message["content"]
                for item in messages
                if isinstance(item, dict)
            ):
                continue
            if messages[-1].get("role") == "user":
                messages.insert(len(messages) - 1, contract_message)
            else:
                messages.append(contract_message)
    return messages
