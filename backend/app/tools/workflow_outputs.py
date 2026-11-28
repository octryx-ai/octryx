"""Phase outputs as chat tools: a run phase submits its structured artefact (``phase_outputs``)."""

from __future__ import annotations

from typing import Any

from .context import ToolContext


class _SubmitPhaseOutputTool:
    name = ""
    description = ""

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ..services.workflow_runs.phase_outputs import submit_output
        from ..services.workflow_runs.records import WorkflowRunError, active_run_for_session, lock_run

        if not context.db or not context.session_id:
            return {"status": "refused", "error": "no_session"}
        run = await active_run_for_session(context.db, context.session_id)
        if run is None or run.status != "running":
            return {"status": "refused", "error": "not_a_run_phase"}
        try:
            run = await lock_run(context.db, run)
        except WorkflowRunError as error:
            return {"status": "refused", "error": error.code}
        from ..models import User
        from ..services.workflow_runs.specification.integration import KINDS

        # The actual caller: a spec-bound engineering contract checks the accepted spec as this user.
        # The caller's session: a parallel_work item records its result on its own item (``teamwork.outputs``).
        extra = {"principal": await context.db.get(User, context.user_id), "session_id": context.session_id}
        if self.name in {f"submit_{kind}" for kind in KINDS}:
            extra.update(request_id=context.request_id,
                         tool_history=context.turn_tool_history)
            if extra["principal"] is None:
                return {"status": "refused", "error": "user_inactive"}
        answer = await submit_output(context.db, run, self.name, params, **extra)
        if answer["state"] != "recorded":
            return {"status": "refused", "error": answer.get("reason"), "message": answer.get("message"),
                    "problems": answer.get("problems") or []}
        await context.db.commit()
        return {"status": "recorded", **{key: value for key, value in answer.items() if key != "state"}}


class SubmitDefinitionOfReadyTool(_SubmitPhaseOutputTool):
    name = "submit_definition_of_ready"
    description = "Record the Work item's Definition of Ready for the workflow run's triage."


class SubmitTestContractTool(_SubmitPhaseOutputTool):
    name = "submit_test_contract"
    description = "Submit the workflow run's test contract: acceptance criteria, their tests and commands."


class SubmitReproductionTool(_SubmitPhaseOutputTool):
    name = "submit_reproduction"
    description = "Submit the tests that reproduce the bug and the symptom they show."


class SubmitIncidentHypothesisTool(_SubmitPhaseOutputTool):
    name = "submit_incident_hypothesis"
    description = "Submit the incident's most likely cause, impact, next step and cited sources."


class SubmitFeatureDocumentationTool(_SubmitPhaseOutputTool):
    name = "submit_feature_documentation"
    description = "Submit the feature documentation (title, what, why, how to use) for the person to confirm."


class SubmitPhaseResultTool(_SubmitPhaseOutputTool):
    name = "submit_phase_result"
    description = "Record the result the workflow run's phase ends with (one of its possible results)."


class SubmitWorkPlanTool(_SubmitPhaseOutputTool):
    name = "submit_work_plan"
    description = "Submit the coordinator's work plan: the shared contract and the items the agents build in parallel."


class SubmitChangePlanTool(_SubmitPhaseOutputTool):
    name = "submit_change_plan"
    description = "Submit the change plan as data: parts, paths, endpoints, expensive path classes, risks, questions."


class SubmitStoryPlanTool(_SubmitPhaseOutputTool):
    name = "submit_story_plan"
    description = "Submit the epic's stories in build order: title, goal, criteria, spec sections, dependencies."


class SubmitSpecStudioTool(_SubmitPhaseOutputTool):
    name = "submit_spec_studio"
    description = ("Submit the structured spec the product owner reviews in the Spec Studio: design tokens, screens "
                   "with mock data, questions, rules with worked examples, acceptance criteria.")


__all__ = ["SubmitDefinitionOfReadyTool", "SubmitFeatureDocumentationTool", "SubmitIncidentHypothesisTool",
           "SubmitPhaseResultTool", "SubmitReproductionTool", "SubmitSpecStudioTool", "SubmitStoryPlanTool",
           "SubmitTestContractTool", "SubmitWorkPlanTool"]
