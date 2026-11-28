"""``@octryx fix`` / ``@octryx write tests`` ."""

from __future__ import annotations

import fnmatch
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...models.runtime.code_intelligence import CodeRepository
from ..workflow_runs import safe_git
from ..workflow_runs.platform.dispatch import FAILED, SUCCEEDED, ToolOutcome
from .providers import mention
from .starter import CONTEXT_KEY

FIX_KEY = "pr-fix"
FIX_PREPARE, FIX_SCOPE, FIX_REPORT = "pr_review.fix_prepare", "pr_review.fix_scope", "pr_review.fix_report"
MODE_FIX, MODE_TESTS = "fix", "tests"
ENGINES = ("claude", "codex")
DEFAULT_TEST_GLOBS = ("test/**", "tests/**", "**/test_*.py", "**/*_test.py", "**/*_test.go", "**/*.test.ts",
                      "**/*.test.tsx", "**/*.spec.ts", "**/*_test.dart", "**/*Test.java", "**/*Test.kt")


def _facts(run: WorkflowRun) -> dict[str, Any]:
    return dict(dict(run.context or {}).get(CONTEXT_KEY) or {})


async def running_fix(db: AsyncSession, project_id: str, repository: str, pr_id: str) -> str:
    rows = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.project_id == project_id, WorkflowRun.workflow_key == FIX_KEY,
        WorkflowRun.repository == repository, WorkflowRun.completed_at.is_(None)))).scalars().all()
    return next((row.id for row in rows if str(_facts(row).get("pr_id")) == str(pr_id)), "")


async def refusal(db: AsyncSession, project_id: str, record: CodeRepository | None, pr: Any, *,
                  running: bool = True) -> str:
    from .settings import settings_of

    settings = settings_of(record)
    if record is None or not settings.fix_runs:
        return "fix runs are off for this repository (a Workspace admin switches them on in the PR review bot settings)"
    if pr is None:
        return "the pull request is not open"
    if pr.fork:
        return "the pull request comes from a fork: Octryx does not push to forks"
    if pr.source_branch == pr.target_branch or pr.source_branch in settings.protected_branches:
        return f"the branch '{pr.source_branch}' is protected: Octryx never pushes to it"
    if running and await running_fix(db, project_id, pr.repository, pr.pr_id):
        return "a fix run is already running on this pull request"
    return ""


# Where a platform administrator (not a Workspace admin) switches an optional workflow on (feat/workflow-active-switch).
WORKFLOWS_PAGE = "Agents › Workflows"  # the rail, then "Workflows" under "Build"


async def switched_off(db: AsyncSession, project_id: str, mode: str) -> str:
    from sqlalchemy import or_

    from ...models.runtime.flow_definition import FlowDefinition
    from ..workflow_runs.engine import published_phased_flow

    if await published_phased_flow(db, FIX_KEY, project_id) is not None:
        return ""
    flows = (await db.execute(select(FlowDefinition).where(
        FlowDefinition.key == FIX_KEY,
        or_(FlowDefinition.project_id.is_(None), FlowDefinition.project_id == project_id)))).scalars().all()
    name = next((flow.name for flow in sorted(flows, key=lambda flow: 0 if flow.project_id else 1) if flow.name),
                FIX_KEY)
    what = "Writing tests for pull requests" if mode == MODE_TESTS else "Fixing pull requests"
    return (f"{what} is switched off on this Octryx installation. A platform administrator can turn on the '{name}' "
            f"workflow under {WORKFLOWS_PAGE}.")


def parse_args(words: str) -> tuple[str, str]:
    first, _, rest = words.strip().partition(" ")
    return (first.lower(), rest.strip()) if first.lower() in ENGINES else ("", words.strip())


async def device_target(db: AsyncSession, user_id: str, repository: str) -> dict[str, Any] | str:
    from ...models.security.device import DEVICE_STATUS_ACTIVE, UserDevice

    name = repository.rstrip("/").rsplit("/", 1)[-1].lower()
    devices = (await db.execute(select(UserDevice).where(
        UserDevice.owner_user_id == user_id, UserDevice.status == DEVICE_STATUS_ACTIVE,
    ).order_by(UserDevice.name))).scalars().all()
    for device in devices:
        if "seat" not in [str(item) for item in device.profiles or []]:
            continue
        folder = next((str(item) for item in device.folders or []
                       if str(item).rstrip("/").rsplit("/", 1)[-1].lower() == name), "")
        if folder:
            return {"kind": "device", "device_id": device.id, "folder": folder, "profile": "seat"}
    return "auto"


async def start_fix(db: AsyncSession, project_id: str, pr: Any, event: Any, user_id: str, *, mode: str,
                    findings: list[dict[str, Any]], note: str, engine: str) -> str:
    from ...models import User
    from ..workflow_runs.phase_outputs import HANDOFF_KEY
    from ..workflow_runs.records import new_chat_session, start_run

    user = await db.get(User, user_id)
    session = await new_chat_session(db, user, project_id)
    asked = {"mode": mode, "note": note, "engine": engine, "comment_id": event.comment_id, "author": event.author,
             "thread_root": event.thread_root, "inline": event.inline,
             "findings": [item.get("id") for item in findings]}
    seed = {"verdict": "changes", "summary": "", "node_id": "independent_review",
            "findings": [{key: item[key] for key in ("id", "severity", "file", "line", "fix") if key in item}
                         for item in findings]} if findings else None
    handoff = {"pr_fix": {"mode": mode, "note": note, "pull_request": {
        "number": pr.pr_id, "title": pr.title, "url": pr.url, "branch": pr.source_branch, "target": pr.target_branch},
        "findings": [{key: item.get(key) for key in ("id", "severity", "file", "line", "fix", "suggestion")
                      if item.get(key)} for item in findings]}}
    run = await start_run(db, user=user, workflow_key=FIX_KEY, project_id=project_id, repository=pr.repository,
                          branch=pr.source_branch, session=session,
                          runtime_target=await device_target(db, user_id, pr.repository), context={
                              CONTEXT_KEY: {**pr.as_context(), "trigger": "command", "fix": asked},
                              HANDOFF_KEY: handoff, **({"review": seed} if seed else {})})
    run.pull_request = {"id": pr.pr_id, "url": pr.url, "title": pr.title}
    # The pushed commit says what it fixes (not just "PR fix").
    run.title, body = commit_message(mode, findings, pr, event)
    run.context = {**dict(run.context or {}), "commit_body": body}
    await db.commit()
    return run.id


def commit_message(mode: str, findings: list[dict[str, Any]], pr: Any, event: Any) -> tuple[str, str]:
    from .ci_results import short

    ids = ", ".join(str(item.get("id")) for item in findings)
    subject = (f"Add tests for pull request #{pr.pr_id} (octryx review)" if mode == MODE_TESTS or not findings else
               f"Fix {ids}: {short(str(findings[0].get('fix') or ''), 60)} (octryx review)")
    lines = [f"- {item.get('id')} {item.get('file')}:{item.get('line')} [{item.get('severity')}] {item.get('fix')}"
             for item in findings]
    who = mention(pr.provider, str(event.author))
    body = "\n".join([*lines, *([""] if lines else []), f"Pull request: {pr.url or '#' + str(pr.pr_id)}",
                      f"Requested by {who} with @octryx {'write tests' if mode == MODE_TESTS else 'fix'}."])
    return subject[:200], body


async def fix_prepare(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> ToolOutcome:
    from ..workflow_runs.platform.scm import checkout
    from .settings import repository_record

    facts = _facts(run)
    record = await repository_record(db, str(run.project_id), str(run.repository))
    pr = _event_of(facts)
    refused = await refusal(db, str(run.project_id), record, pr, running=False)
    if refused:
        return ToolOutcome(FAILED, reason=refused)
    checked = await checkout(db, run, {"base_branch": str(facts.get("target_branch") or "")})
    if not checked.ok:
        return checked
    root = str(checked.result.get("local_path") or "")
    code, head, _err = await safe_git.git(root, "rev-parse", "HEAD")
    if code != 0 or not head.strip():
        return ToolOutcome(FAILED, reason="the pull request's branch has no head commit")
    # The fix is the change from the pull request's head: the reviewer reviews it, the push lands on top of it.
    run.context = {**dict(run.context or {}), "base_sha": head.strip(),
                   CONTEXT_KEY: {**facts, "fix_base": head.strip()}}
    return ToolOutcome(SUCCEEDED, {"local_path": root, "base_sha": head.strip()})


def _event_of(facts: dict[str, Any]) -> Any:
    from .events import PullRequestEvent

    fields = PullRequestEvent.__dataclass_fields__
    return PullRequestEvent(**{key: facts[key] for key in fields if key in facts}) if facts.get("pr_id") else None


async def _changed(run: WorkflowRun) -> list[str]:
    from ..workflow_runs.review.convergence import changed_paths

    context = dict(run.context or {})
    patch = str(dict(context.get("device_change") or {}).get("patch") or "")
    if patch:
        return list(changed_paths(patch))
    root, base = str(context.get("local_path") or ""), str(context.get("base_sha") or "")
    if not root or not base:
        return []
    changed = (await safe_git.git(root, "diff", "--name-only", base))[1].splitlines()
    untracked = (await safe_git.git(root, "ls-files", "--others", "--exclude-standard"))[1].splitlines()
    return sorted({path.strip() for path in [*changed, *untracked] if path.strip()})


async def _test_globs(db: AsyncSession, run: WorkflowRun) -> list[str]:
    from ..workflow_runs.octryx.code_limits import phase_style

    style = await phase_style(db, run, "change") or {}
    globs = [str(item) for item in dict(style.get("general") or {}).get("test_globs") or [] if str(item).strip()]
    return globs or list(DEFAULT_TEST_GLOBS)


def is_test(path: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, glob) or fnmatch.fnmatch(path, glob.removeprefix("**/")) for glob in globs)


async def fix_scope(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> ToolOutcome:
    changed = await _changed(run)
    if not changed:
        return ToolOutcome(FAILED, reason="the agent changed nothing")
    if dict(_facts(run).get("fix") or {}).get("mode") == MODE_TESTS:
        globs = await _test_globs(db, run)
        other = [path for path in changed if not is_test(path, globs)]
        if other:
            return ToolOutcome(FAILED, reason="`write tests` may only add or change tests; it also changed "
                                              + ", ".join(other[:5]))
    return ToolOutcome(SUCCEEDED, {"changed": changed})


def _last_failure(run: WorkflowRun) -> str:
    actions = dict(dict(run.context or {}).get("actions") or {})
    failed = [dict(item) for item in actions.values() if dict(item).get("result") == FAILED]
    if failed:
        reason = str(failed[-1].get("reason") or f"the step {failed[-1].get('action') or ''} failed").strip()
        if "operation 'branch'" in reason or "operation 'write'" in reason:
            reason += (" (a fix run needs the repository's branch and write operations: a Workspace admin allows them "
                       "in the repository's settings)")
        return reason
    review = dict(dict(run.context or {}).get("review") or {})
    reviewed = bool(review.get("attempt"))  # the run's own review; the findings it started with carry no attempt
    open_findings = [f"{item.get('file')}:{item.get('line')} {item.get('fix')}" for item in review.get("findings")
                     or [] if isinstance(item, dict)]
    if reviewed and review.get("verdict") == "changes" and open_findings:
        return "the independent review did not pass the fix: " + "; ".join(open_findings[:3])
    return "the run stopped before the push"


async def fix_report(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> ToolOutcome:
    from .comment_events import CommentEvent
    from .explain import reply_in_pr

    facts = _facts(run)
    asked = dict(facts.get("fix") or {})
    head = str(dict(run.context or {}).get("head_sha") or "")
    pushed = params.get("outcome") == "pushed" and head
    what = "adds tests" if asked.get("mode") == MODE_TESTS else (
        f"fixes {', '.join(asked['findings'])}" if asked.get("findings") else "a fix")
    text = (f"🔧 Octryx pushed `{head[:7]}` to `{run.branch}`: {what} (run `{run.id}`). The next review pass checks "
            "it." if pushed else f"Octryx could not finish the {'tests' if asked.get('mode') == MODE_TESTS else 'fix'}"
            f": {_last_failure(run)} (run `{run.id}`). Nothing was pushed.")
    event = CommentEvent(str(run.repository), str(facts.get("pr_id")), str(asked.get("comment_id") or ""),
                         str(asked.get("author") or ""), "", in_reply_to=str(asked.get("thread_root") or ""),
                         inline=bool(asked.get("inline")))
    posted = await reply_in_pr(db, run, event, text)
    run.context = {**dict(run.context or {}), CONTEXT_KEY: {**facts, "fix_reported": posted.ok,
                                                             "fix_pushed": bool(pushed)}}
    return ToolOutcome(SUCCEEDED, {"reported": posted.ok, "pushed": bool(pushed)})


HANDLERS = {FIX_PREPARE: fix_prepare, FIX_SCOPE: fix_scope, FIX_REPORT: fix_report}

__all__ = ["DEFAULT_TEST_GLOBS", "FIX_KEY", "FIX_PREPARE", "FIX_REPORT", "FIX_SCOPE", "HANDLERS", "MODE_FIX",
           "MODE_TESTS", "commit_message", "device_target", "fix_prepare", "fix_report", "fix_scope", "is_test",
           "parse_args", "refusal", "running_fix", "start_fix", "switched_off"]
