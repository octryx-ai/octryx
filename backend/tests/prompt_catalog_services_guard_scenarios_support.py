"""Fixed inputs for the services prompt-builder golden scenarios of secure work and tool guards."""

from __future__ import annotations


def _secure_work() -> dict[str, str]:
    from app.services.secure_work.coding.verification_contract import verification_contract_prompt_lines

    contracts = {
        "none": None,
        "commands": {"commands": [{"command": "make test", "source": "change_unit"}]},
        "criteria": {
            "commands": [{"command": "make test", "source": "change_unit"}],
            "acceptance_criteria": [{"id": "AC1", "text": "Works."}, "skip"],
        },
    }
    outputs: dict[str, str] = {}
    for name, contract in contracts.items():
        outputs[f"secure_work:verification:{name}"] = "\n".join(verification_contract_prompt_lines(contract))
    return outputs


def _tool_guard() -> dict[str, str]:
    from app.services.tool_artifact.working_set import _build_collapsed_tool_history_summary

    outputs: dict[str, str] = {}
    envelopes = [
        {"artifact_id": "a1", "summary": "Listed pods", "salient_facts": ["3 pods", "1 failing", "x"]},
        {"artifact_id": "a2", "summary": "Logs", "salient_facts": []},
    ]
    outputs["tool_guard:collapsed"] = repr(
        _build_collapsed_tool_history_summary(envelopes, removed_tool_names=["a", "b", "c"])
    )
    outputs["tool_guard:collapsed:no_names"] = repr(_build_collapsed_tool_history_summary(envelopes, removed_tool_names=[]))
    return outputs
