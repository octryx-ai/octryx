"""Fixed inputs for the services prompt-builder golden scenarios of secure work and tool guards.

``scenario_outputs`` in ``prompt_catalog_services_scenarios_support`` runs these groups with the others.
"""

from __future__ import annotations


def _secure_work() -> dict[str, str]:
    from types import SimpleNamespace

    from app.services.secure_work.coding.coding_workspaces import workspace_prompt_lines
    from app.services.secure_work.coding.execution_prompt import _agent_execution_prompt
    from app.services.secure_work.coding.verification_contract import verification_contract_prompt_lines

    item = SimpleNamespace(
        source_key="RIVER-1", title="Fix it", source_status="In Progress", source_url="https://j/RIVER-1",
        description="Do the thing.",
    )
    bare_item = SimpleNamespace(source_key="RIVER-2", title="T", source_status=None, source_url=None, description=None)
    plan = SimpleNamespace(
        version=3, title="Plan", understood_request="Understood.", rollback_plan="Revert.",
        validation_plan_json=[{"command": "pytest -q"}],
    )
    bare_plan = SimpleNamespace(version=1, title="P", understood_request=None, rollback_plan=None, validation_plan_json=[])
    unit = SimpleNamespace(
        repository_name="repo", branch_name="feat", scope="", expected_paths_json=["a.py"],
        validation_commands_json=["make test"],
    )
    run = {
        "id": "run-1",
        "status": "prepared",
        "summary": {
            "state_machine": {
                "version": 2, "phase": "edited", "status": "open",
                "next_action": {"key": "edit_or_block", "label": "Apply scoped changes."},
                "required_evidence": ["changes_made"], "evidence": {"workspace_prepared": True},
                "blockers": [{"code": "x"}],
            }
        },
    }
    workspaces = [
        {"repository_slug": "repo", "project_key": "OCX", "feature_branch": "feat", "base_branch": "main",
         "workspace_path": "/w", "status": "prepared_empty"},
        {"repository_name": "other", "status": "prepared"},
    ]
    contracts = {
        "none": None,
        "commands": {"commands": [{"command": "make test", "source": "change_unit"}]},
        "criteria": {
            "commands": [{"command": "make test", "source": "change_unit"}],
            "acceptance_criteria": [{"id": "AC1", "text": "Works."}, "skip"],
        },
    }
    outputs = {
        "secure_work:prompt:full": _agent_execution_prompt(
            item=item, plan=plan, units=[unit], pipeline_run=run,
            payload={"restart_from_scratch": True, "operator_note": "Go."}, workspaces=workspaces,
        ),
        "secure_work:prompt:bare": _agent_execution_prompt(
            item=bare_item, plan=bare_plan, units=[], pipeline_run={}, payload={}, workspaces=None,
        ),
        "secure_work:workspaces:empty": "\n".join(workspace_prompt_lines([])),
    }
    for name, contract in contracts.items():
        outputs[f"secure_work:verification:{name}"] = "\n".join(verification_contract_prompt_lines(contract))
    return outputs


def _tool_guard() -> dict[str, str]:
    from app.agent.engine.messages._engine_message_helpers import _build_current_step_prompt
    from app.services.tool_artifact.working_set import _build_collapsed_tool_history_summary
    from app.services.tool_result_compression.strategy_aws import _topology_answer_guidance
    from app.services.turn_tool_guards import coding_intelligence_guard_result

    outputs: dict[str, str] = {}
    steps = {
        "plain": ({"name": "Inspect", "stepType": "analysis", "instructions": "Read.", "successCriteria": "Done."}, None),
        "tools": (
            {"name": "", "allowedTools": ["read_file", "grep"], "tddCyclePhaseTitle": "Make Green",
             "tddCyclePhaseIndex": 2, "tddCyclePhaseTotal": 3, "tddCyclePhaseInstructions": "Go green."},
            "feat",
        ),
        "tdd_unknown": ({"name": "S", "tddCyclePhaseTitle": "T"}, None),
    }
    for name, (step, prefix) in steps.items():
        outputs[f"tool_guard:step:{name}"] = _build_current_step_prompt(step, 2, 4, prefix)
    envelopes = [
        {"artifact_id": "a1", "summary": "Listed pods", "salient_facts": ["3 pods", "1 failing", "x"]},
        {"artifact_id": "a2", "summary": "Logs", "salient_facts": []},
    ]
    outputs["tool_guard:collapsed"] = repr(
        _build_collapsed_tool_history_summary(envelopes, removed_tool_names=["a", "b", "c"])
    )
    outputs["tool_guard:collapsed:no_names"] = repr(_build_collapsed_tool_history_summary(envelopes, removed_tool_names=[]))
    for brief in (True, False):
        for detail in ("compact", "full"):
            outputs[f"tool_guard:aws_guidance:{brief}:{detail}"] = repr(
                _topology_answer_guidance(brief, diagram_detail=detail)
            )
    outputs["tool_guard:prewrite"] = repr(
        coding_intelligence_guard_result(
            tool_name="write_workspace_file",
            tool_args={"path": "app/x.py"},
            turn_tool_history=[],
            capability_type="change",
        )
    )
    return outputs
