"""What the workflow designer's side panel offers to choose from (designer D2b, ``DesignerCatalog``).

``GET /api/v1/phased-workflows/catalog``: the agents a phase can run as (with their capability ceiling), the tools a
phase may allow, the check types (a phase's "done when" and what a gate can judge), the published workflows a
sub-workflow can run, the typed platform actions with their routes, the closed values of the person boxes and the
work item fields a condition can compare. Every list comes from the backend vocabulary the validator
(``graph.validate_phased_definition``) reads, so the panel never offers a value a draft could not publish with.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import FlowDefinition
from ...models.runtime.flow_definition import FlowDefinitionVersion
from ..work_role_model.seeds import WORK_ROLE_KEYS
from .graph import (
    CONFIRMATION_SUBJECTS,
    GATE_CHECK_TYPES,
    WATCH_CONDITIONS,
    is_phased_definition,
)
from .states import OUTCOMES

# The parameters the side panel offers per check type (``workflow_checks.library.evaluate`` reads them); a list
# parameter ends in "s" ("tools", "values", "tests").
CHECK_PARAMS: dict[str, list[str]] = {
    "tool_called": ["tools"],
    "tool_not_called": ["tools"],
    "evidence_count": ["tools", "min_count"],
    "artifact_created": ["artifact_type", "min_count"],
    "answer_contains_any": ["values"],
    "urls_cited": ["min_count", "path"],
    "field_present": ["tool", "field", "min_count"],
    "tests_red": ["tests"],
    "tests_green": ["tests"],
    "confirmed_tests_intact": ["tests"],
    "reproduces": ["tests", "regression", "symptom"],
    "specification_ready": ["kind"],
    "evidence_families": ["required"],
}

CHECK_LABELS: dict[str, str] = {
    "tool_called": "A tool was called",
    "tool_not_called": "A tool was not called",
    "evidence_count": "Enough evidence collected",
    "artifact_created": "An artifact was created",
    "citations_present": "The answer cites its sources",
    "urls_cited": "Sources cited as URLs",
    "answer_contains_any": "The answer contains a phrase",
    "field_present": "A field is present",
    "test_command_passed": "The test command passed",
    "tests_red": "Tests fail first (red)",
    "tests_green": "Tests pass (green)",
    "confirmed_tests_intact": "Confirmed tests unchanged",
    "ci_green": "CI is green",
    "reproduces": "The problem is reproduced",
    "review_passed": "The review passed",
    "artefact_review_passed": "The artefact review passed",
    "slices_merged": "Every slice is merged",
    "definition_of_ready": "Definition of Ready complete",
    "specification_ready": "Specification ready",
    "lint_passed": "Lint passed",
    "ci_findings_addressed": "CI findings addressed",
    "evidence_families": "Every evidence family answered",
    "judge": "Judge (advisory)",
}

ACTION_LABELS: dict[str, str] = {
    "jira.create_issue": "Create the Jira issue",
    "jira.comment": "Comment on the Jira issue",
    "jira.transition": "Move the Jira issue",
    "scm.create_branch": "Create a branch",
    "scm.push": "Push the commits",
    "scm.open_pr": "Open a pull request",
    "scm.checkout": "Check out the branch",
    "scm.comment": "Comment on the pull request",
    "ci.status": "Read the CI status",
    "deploy.configured": "Check whether a deploy job exists",
    "deploy.run": "Run the deploy job",
    "work.draft_change_plan": "Draft the change plan",
    "work.create_stories": "Create the epic's stories",
    "workspace.prepare": "Prepare the working folder",
    "documentation.publish_spec": "Publish the spec page",
    "documentation.publish_feature": "Publish the feature and epic pages",
}

DECIDERS: tuple[str, ...] = ("requester", "item_owner", "handoff_owner", "spec_origin")
_DEFAULT_ACTION_ROUTES = ("succeeded", "failed")


def _words(value: str) -> str:
    text = value.replace(".", " ").replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else value


async def _agents(db: AsyncSession) -> list[dict[str, str]]:
    from ..platform_agents.published import published_platform_agent
    from ..platform_agents.seeds import SEEDS_BY_KEY
    from .phase_agents import PHASE_AGENT_KEYS

    agents: list[dict[str, str]] = []
    for key in PHASE_AGENT_KEYS:
        seed = SEEDS_BY_KEY[key]
        published = await published_platform_agent(db, key)
        if published is not None and not published.active:
            continue
        name = (published.name if published is not None and published.name else "") or seed.name
        agents.append({"key": key, "name": name, "capability_ceiling": seed.capability_ceiling})
    return agents


def _tools() -> list[str]:
    from ...tools.definitions.connector_ownership import SERVICE_ONLY_TOOLS
    from ...tools.registry import TOOL_REGISTRY

    return sorted(TOOL_REGISTRY.keys() - SERVICE_ONLY_TOOLS)


def _check_types() -> list[dict[str, Any]]:
    from ..workflow_checks.library import CHECK_TYPES

    return [{"type": kind, "label": CHECK_LABELS.get(kind, _words(kind)), "params": list(CHECK_PARAMS.get(kind, []))}
            for kind in CHECK_TYPES]


def _platform_actions() -> list[dict[str, Any]]:
    from .platform.catalog import ACTION_ROUTES, ACTIONS

    return [{"key": key, "label": ACTION_LABELS.get(key, _words(key)),
             "routes": sorted(ACTION_ROUTES.get(key) or _DEFAULT_ACTION_ROUTES)}
            for key in sorted(ACTIONS)]


async def _workflows(db: AsyncSession) -> list[dict[str, str]]:
    """The published, active phased workflows a sub-workflow box can run (one entry per key)."""
    rows = (await db.execute(
        select(FlowDefinition.key, FlowDefinition.name, FlowDefinitionVersion.definition_json)
        .join(FlowDefinitionVersion, FlowDefinitionVersion.id == FlowDefinition.current_version_id)
        .where(FlowDefinition.status == "published", FlowDefinition.is_active.is_(True),
               FlowDefinitionVersion.status == "published")
    )).all()
    seen: dict[str, str] = {}
    for key, name, definition in rows:
        if key not in seen and is_phased_definition(dict(definition or {})):
            seen[key] = name or key
    return [{"key": key, "title": title} for key, title in sorted(seen.items(), key=lambda item: item[1].lower())]


async def designer_catalog(db: AsyncSession, *, project_id: str | None = None) -> dict[str, Any]:
    from .work_item_fields import work_item_fields

    return {
        "agents": await _agents(db),
        "tools": _tools(),
        "checkTypes": _check_types(),
        "gateCheckTypes": sorted(GATE_CHECK_TYPES),
        "workflows": await _workflows(db),
        "platformActions": _platform_actions(),
        "confirmationSubjects": sorted(CONFIRMATION_SUBJECTS),
        "watchConditions": sorted(WATCH_CONDITIONS),
        "outcomes": sorted(OUTCOMES),
        "deciders": [*DECIDERS, *(f"role:{key}" for key in sorted(WORK_ROLE_KEYS))],
        # What a field condition can compare (D2b2), with the values the Workspace's work items have.
        "workItemFields": await work_item_fields(db, project_id=project_id),
        # Teamwork: the "Parallel work" box (fork/join) — its routes, the plan output it runs, the suggested roles.
        "parallelWork": parallel_work_catalog(),
    }


PARALLEL_ROLES = ("backend", "frontend", "test")


def parallel_work_catalog() -> dict[str, Any]:
    from .teamwork import OUTPUT_KIND, OUTPUT_TOOL, ROUTE_DONE, ROUTE_REPLAN

    return {"kind": "parallel_work", "label": "Parallel work",
            "subtitle": f"{' · '.join(PARALLEL_ROLES)} — split at run time",
            "routes": [ROUTE_DONE, ROUTE_REPLAN], "loopRoute": ROUTE_REPLAN,
            "planOutput": OUTPUT_KIND, "planTool": OUTPUT_TOOL, "suggestedRoles": list(PARALLEL_ROLES),
            "roleKeys": ["agent", "model", "workflow_contract", "tool_policy", "workflow_id", "workflow_class",
                         "needs_proof"]}


__all__ = ["designer_catalog"]
