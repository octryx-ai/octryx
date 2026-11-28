"""The closed catalog of typed platform actions a phased workflow can name."""


from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..documentation.s1_graph import S1_ACTION_CLASSES, S1_ACTION_PARAMS, S1_ACTION_ROUTES


@dataclass(frozen=True, slots=True)
class ActionSpec:
    key: str
    capability_class: str
    params: frozenset[str]
    required: frozenset[str] = frozenset()
    choices: tuple[tuple[str, frozenset[str]], ...] = ()
    # An octryx-claude session may ask for it (``workflow_action_request``); a definition-only step may not.
    requestable: bool = True
    # A check a workflow's size class may skip (``size_classes.skip_nodes``): its result is no evidence a later step
    # needs. Never a push, a pull request, a ticket or a report.
    skippable: bool = False


JIRA_CREATE_ISSUE = "jira.create_issue"
JIRA_COMMENT = "jira.comment"
JIRA_TRANSITION = "jira.transition"
SCM_CREATE_BRANCH = "scm.create_branch"
SCM_PUSH = "scm.push"
SCM_OPEN_PR = "scm.open_pr"
CI_STATUS = "ci.status"
SCM_CHECKOUT = "scm.checkout"
SCM_COMMENT = "scm.comment"
DEPLOY_CONFIGURED = "deploy.configured"
DEPLOY_RUN = "deploy.run"
WORK_DRAFT_CHANGE_PLAN = "work.draft_change_plan"
WORK_CREATE_STORIES = "work.create_stories"
WORKSPACE_PREPARE = "workspace.prepare"
PIPELINE_RUN = "pipeline.run"
HANDS_ON_RUN = "hands_on.run"
BUG_INTAKE_CHECK = "bug.intake_check"
BUG_REPORT = "bug.report"
PUBLISH_SPEC = "documentation.publish_spec"
PUBLISH_FEATURE = "documentation.publish_feature"
SKIPPED = "skipped"
DOCUMENTATION_ROUTES = frozenset({"succeeded", "failed", SKIPPED})

TEXT_SOURCES = frozenset({"work_item", "phase_answer", "findings", "pull_request", "review", "dor_questions",
                          "hypothesis"})
ACTIONS: dict[str, ActionSpec] = {
    JIRA_CREATE_ISSUE: ActionSpec(
        JIRA_CREATE_ISSUE, "deliver", frozenset({"issue_type", "project_key", "summary_from", "description_from",
                                                  "follow_up"}),
        frozenset({"issue_type"}),
        (("summary_from", TEXT_SOURCES), ("description_from", TEXT_SOURCES)),
    ),
    JIRA_COMMENT: ActionSpec(JIRA_COMMENT, "deliver", frozenset({"text_from"}), frozenset({"text_from"}),
                             (("text_from", TEXT_SOURCES),)),
    JIRA_TRANSITION: ActionSpec(JIRA_TRANSITION, "deliver", frozenset({"work_state"}), frozenset({"work_state"})),
    SCM_CREATE_BRANCH: ActionSpec(SCM_CREATE_BRANCH, "deliver", frozenset({"branch_type"})),
    SCM_PUSH: ActionSpec(SCM_PUSH, "deliver", frozenset()),
    SCM_OPEN_PR: ActionSpec(SCM_OPEN_PR, "deliver", frozenset({"target_branch"})),
    CI_STATUS: ActionSpec(CI_STATUS, "read_only", frozenset({"job", "workflow"})),
    SCM_CHECKOUT: ActionSpec(SCM_CHECKOUT, "change", frozenset({"base_branch"})),
    SCM_COMMENT: ActionSpec(SCM_COMMENT, "deliver", frozenset({"text_from"}), frozenset({"text_from"}),
                            (("text_from", TEXT_SOURCES),)),
    DEPLOY_CONFIGURED: ActionSpec(DEPLOY_CONFIGURED, "read_only", frozenset()),
    DEPLOY_RUN: ActionSpec(DEPLOY_RUN, "deliver", frozenset()),
    WORK_DRAFT_CHANGE_PLAN: ActionSpec(WORK_DRAFT_CHANGE_PLAN, "change", frozenset(), requestable=False),
    WORKSPACE_PREPARE: ActionSpec(WORKSPACE_PREPARE, "change", frozenset(), requestable=False),
    WORK_CREATE_STORIES: ActionSpec(WORK_CREATE_STORIES, "deliver", frozenset({"issue_type", "story_workflow"}),
                                    requestable=False),
    PIPELINE_RUN: ActionSpec(PIPELINE_RUN, "read_only", frozenset(), requestable=False),
    HANDS_ON_RUN: ActionSpec(HANDS_ON_RUN, "read_only", frozenset(), requestable=False, skippable=True),
    BUG_INTAKE_CHECK: ActionSpec(BUG_INTAKE_CHECK, "read_only", frozenset(), requestable=False),
    BUG_REPORT: ActionSpec(BUG_REPORT, "deliver", frozenset({"event"}), frozenset({"event"}),
                           (("event", frozenset({"cannot_reproduce", "fixed", "released"})),), requestable=False),
    PUBLISH_SPEC: ActionSpec(PUBLISH_SPEC, "deliver", frozenset(), requestable=False),
    PUBLISH_FEATURE: ActionSpec(PUBLISH_FEATURE, "deliver", frozenset(), requestable=False),
}
# Raw Jira status vocabulary is never a workflow parameter: the write-back mapping owns it.
FORBIDDEN_PARAMS = frozenset({"status", "jira_status", "transition", "transition_id"})


def validate_action_config(node_id: str, config: dict[str, Any]) -> list[dict[str, str]]:
    def error(code: str, message: str) -> list[dict[str, str]]:
        return [{"code": code, "message": f"Platform action '{node_id}': {message}"}]

    key = str(config.get("action") or "").strip()
    spec = ACTIONS.get(key)
    if spec is None:
        return error("unknown_platform_action", f"action must be one of: {', '.join(sorted(ACTIONS))}.")
    params = config.get("params") if config.get("params") is not None else {}
    if not isinstance(params, dict):
        return error("action_params", "params must be an object.")
    forbidden = set(params) & FORBIDDEN_PARAMS
    if forbidden:
        return error("raw_status_forbidden", "name a Work state (work_state); the write-back maps it to Jira.")
    unknown = set(params) - spec.params
    if unknown:
        return error("unknown_action_param", f"unknown params: {', '.join(sorted(unknown))}.")
    missing = [name for name in spec.required if not str(params.get(name) or "").strip()]
    if missing:
        return error("missing_action_param", f"needs: {', '.join(sorted(missing))}.")
    for name, allowed in spec.choices:
        if name in params and str(params[name]) not in allowed:
            return error("action_param_value", f"{name} must be one of: {', '.join(sorted(allowed))}.")
    return []


def action_class(config: dict[str, Any]) -> str:
    spec = ACTIONS.get(str(config.get("action") or ""))
    return spec.capability_class if spec is not None else str(config.get("capability_class") or "read_only")


# Routes of a typed action: CI status also routes on ``running`` (not finished yet).
ACTION_ROUTES = {CI_STATUS: frozenset({"succeeded", "failed", "running"}),
                 DEPLOY_CONFIGURED: frozenset({"configured", "not_configured"}),
                 # Nothing configured, no opt-in, a drifted target: ``skipped`` (never a pause).
                 PUBLISH_SPEC: DOCUMENTATION_ROUTES, PUBLISH_FEATURE: DOCUMENTATION_ROUTES,
                 HANDS_ON_RUN: frozenset({"succeeded", "failed", "skipped", "cannot_reproduce"}),
                 BUG_INTAKE_CHECK: frozenset({"succeeded", "incomplete", "failed"})}

# Definition-only contracts; no model/device-requested action surface.

for _key, _capability in S1_ACTION_CLASSES.items():
    _choices = S1_ACTION_PARAMS.get(_key, ())
    ACTIONS[_key] = ActionSpec(_key, _capability, frozenset(name for name, _ in _choices),
                              choices=_choices, requestable=False)
ACTION_ROUTES.update(S1_ACTION_ROUTES)

# The PR review bot's steps (``pr_review_bot.actions``): definition-only, never requested by an agent.
for _key, _capability in (("pr_review.prepare", "deliver"), ("pr_review.publish", "deliver"),
                          ("pr_review.report_failure", "deliver"), ("pr_review.explain", "deliver"),
                          ("pr_review.fix_prepare", "change"), ("pr_review.fix_scope", "read_only"),
                          ("pr_review.fix_report", "deliver")):
    ACTIONS[_key] = ActionSpec(_key, _capability, frozenset({"outcome"}) if _key == "pr_review.fix_report"
                               else frozenset(), requestable=False)

__all__ = [
    "ACTIONS",
    "ACTION_ROUTES",
    "CI_STATUS",
    "DEPLOY_CONFIGURED",
    "DEPLOY_RUN",
    "DOCUMENTATION_ROUTES",
    "JIRA_COMMENT",
    "JIRA_CREATE_ISSUE",
    "JIRA_TRANSITION",
    "PUBLISH_FEATURE",
    "PUBLISH_SPEC",
    "SCM_CHECKOUT",
    "SCM_COMMENT",
    "SCM_CREATE_BRANCH",
    "SCM_OPEN_PR",
    "SCM_PUSH",
    "SKIPPED",
    "WORK_CREATE_STORIES",
    "WORK_DRAFT_CHANGE_PLAN",
    "WORKSPACE_PREPARE",
    "action_class",
    "validate_action_config",
]
