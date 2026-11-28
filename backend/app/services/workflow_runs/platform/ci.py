"""Provider-neutral CI status of the run's branch: ``succeeded`` | ``failed`` | ``running`` | ``unknown``."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ....time_utils import utc_now
from ...workflow_checks.test_output import ParsedTests
from . import ci_tests
from .dispatch import dispatch_tool
from .repo_ref import parse_repository

CI_SUCCEEDED, CI_FAILED, CI_RUNNING, CI_UNKNOWN = "succeeded", "failed", "running", "unknown"
_JENKINS = {"passed": CI_SUCCEEDED, "failed": CI_FAILED, "unstable": CI_FAILED, "running": CI_RUNNING,
            "cancelled": CI_FAILED}
_BITBUCKET = {"SUCCESSFUL": CI_SUCCEEDED, "FAILED": CI_FAILED, "INPROGRESS": CI_RUNNING, "STOPPED": CI_FAILED}
_GITHUB_CONCLUSIONS = {"success": CI_SUCCEEDED, "failure": CI_FAILED, "cancelled": CI_FAILED, "timed_out": CI_FAILED}
_GITLAB = {"success": CI_SUCCEEDED, "failed": CI_FAILED, "canceled": CI_FAILED, "running": CI_RUNNING,
           "pending": CI_RUNNING, "created": CI_RUNNING}


@dataclass(slots=True)
class CiResult:
    provider: str
    state: str
    url: str = ""
    reason: str = ""
    tests: ParsedTests | None = None

    sha: str = ""
    build: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, "state": self.state, "url": self.url, "reason": self.reason,
                "tests": {test_id: value["outcome"] for test_id, value in self.tests.results.items()}
                if self.tests else {}, "sha": self.sha, "build": self.build, "at": utc_now().isoformat()}


def _head(run: WorkflowRun) -> str:
    return str(dict(run.context or {}).get("head_sha") or "")


def _aggregate(states: list[str]) -> str:
    if not states:
        return CI_RUNNING
    if CI_FAILED in states:
        return CI_FAILED
    if CI_RUNNING in states:
        return CI_RUNNING
    return CI_SUCCEEDED if set(states) == {CI_SUCCEEDED} else CI_UNKNOWN


def jenkins_tests(report: dict[str, Any]) -> ParsedTests:
    return ci_tests.jenkins_report(report)


async def _jenkins(db: AsyncSession, run: WorkflowRun, job: str, *, queue_url: str = "",
                   build_number: str = "") -> CiResult:
    from . import deploy

    client = await deploy.jenkins_client(db, run)
    if client is None:
        return CiResult("jenkins", CI_UNKNOWN, reason="no Jenkins connection serves this Workspace")
    if queue_url:
        return await _deploy_build(client, job, queue_url, build_number)
    head = _head(run)
    builds = await client.list_builds(job, limit=20 if head else 1)
    if head:
        builds = [build for build in builds if str(build.get("commit") or "") == head]
        if not builds:
            return CiResult("jenkins", CI_RUNNING, reason=f"job '{job}' has no build of {head[:12]} yet", sha=head)
    if not builds:
        return CiResult("jenkins", CI_UNKNOWN, reason=f"job '{job}' has no build")
    build = builds[0]
    result = CiResult("jenkins", _JENKINS.get(str(build.get("status")), CI_UNKNOWN), str(build.get("build_url") or ""),
                      sha=head)
    if result.state in (CI_SUCCEEDED, CI_FAILED):
        try:
            result.tests = jenkins_tests(await client.get_test_report(job, build["build_number"]))
        except Exception:  # a build without a test report still has its result
            result.tests = None
    return result


async def _deploy_build(client: Any, job: str, queue_url: str, build_number: str = "") -> CiResult:
    # Resolved once: Jenkins forgets a queue item minutes after it left the queue.
    number = build_number or await client.queued_build_number(queue_url)
    if number is None:
        return CiResult("jenkins", CI_RUNNING, reason=f"job '{job}' has not started the queued deploy yet")
    build = await client.get_build_status(job, number)
    return CiResult("jenkins", _JENKINS.get(str(build.get("status")), CI_UNKNOWN), str(build.get("build_url") or ""),
                    build=str(number))


async def _bitbucket(db: AsyncSession, run: WorkflowRun, ref: Any) -> CiResult:
    head = _head(run)
    outcome = await dispatch_tool(db, run, "get_bitbucket_build_statuses",
                                  {**ref.args(), **({"commit": head} if head else {"branch": run.branch}),
                                   "include_test_reports": True}, capability_class="read_only")
    if not outcome.ok:
        return CiResult("bitbucket", CI_UNKNOWN, reason=outcome.reason or f"branch '{run.branch}' not found", sha=head)
    statuses = list(outcome.result.get("statuses") or [])
    if not statuses:
        if head:
            return CiResult("bitbucket", CI_RUNNING, reason="no build status for the pushed commit yet", sha=head)
        return CiResult("bitbucket", CI_UNKNOWN, reason="no build status for the branch head")
    state = _aggregate([_BITBUCKET.get(str(item.get("state")), CI_UNKNOWN) for item in statuses])
    url = next((str(item.get("url") or "") for item in statuses), "")
    tests = ci_tests.bitbucket_tests(statuses) if state in (CI_SUCCEEDED, CI_FAILED) else None
    return CiResult("bitbucket", state, url, sha=head, tests=tests)


def _github_state(item: dict[str, Any]) -> str:
    if item.get("status") != "completed":
        return CI_RUNNING
    return _GITHUB_CONCLUSIONS.get(str(item.get("conclusion")), CI_UNKNOWN)


async def _github(db: AsyncSession, run: WorkflowRun, ref: Any, workflow: str) -> CiResult:
    head = _head(run)
    outcome = await dispatch_tool(db, run, "list_github_action_runs",
                                  {**ref.args(), "branch": run.branch, "limit": 30 if head else 1},
                                  capability_class="read_only")
    runs = list(outcome.result.get("workflow_runs") or []) if outcome.ok else []
    if not head:
        if not runs:
            return CiResult("github", CI_UNKNOWN, reason=outcome.reason or "no Actions run for the branch")
        return CiResult("github", _github_state(runs[0]), str(runs[0].get("html_url") or ""))
    if not outcome.ok:
        if re.search(r"\b(403|404)\b", str(outcome.reason or "")):
            # A connection without Actions read access (403) counts as "no Actions run": after the grace the run goes on
            # and says why.
            return CiResult("github", CI_UNKNOWN, sha=head, reason=(
                f"no Actions run readable for {head[:12]}: the connection cannot read GitHub Actions "
                f"({'403 Forbidden' if '403' in str(outcome.reason) else '404 Not Found'})"))
        return CiResult("github", CI_UNKNOWN, reason=outcome.reason, sha=head)
    mine = [item for item in runs if str(item.get("head_sha") or "") == head
            and (not workflow or str(item.get("name") or "") == workflow)]
    # Several runs of one workflow for the commit (a re-run): the newest decides for that workflow.
    newest: dict[str, dict[str, Any]] = {}
    for item in mine:
        newest.setdefault(str(item.get("name") or item.get("id")), item)
    state = _aggregate([_github_state(item) for item in newest.values()])
    url = next((str(item.get("html_url") or "") for item in newest.values()), "")
    reason = "" if newest else f"no {('workflow ' + workflow) if workflow else 'Actions run'} for {head[:12]} yet"
    tests = await ci_tests.github_tests(db, run, ref, list(newest.values())) if state in (
        CI_SUCCEEDED, CI_FAILED) else None
    return CiResult("github", state, url, reason, sha=head, tests=tests)


async def _native(db: AsyncSession, run: WorkflowRun, workflow: str = "") -> CiResult:
    ref = parse_repository(run.repository)
    if ref is None or not run.branch:
        return CiResult("none", CI_UNKNOWN, reason="the run has no repository and branch to ask CI about")
    if ref.provider == "bitbucket":
        return await _bitbucket(db, run, ref)
    if ref.provider == "github":
        return await _github(db, run, ref, workflow)
    head = _head(run)
    outcome = await dispatch_tool(db, run, "list_gitlab_pipelines",
                                  {**ref.args(), "ref": run.branch, "limit": 20 if head else 1},
                                  capability_class="read_only")
    pipelines = list(outcome.result.get("pipelines") or []) if outcome.ok else []
    if head and outcome.ok:
        pipelines = [item for item in pipelines if str(item.get("sha") or "") == head]
        if not pipelines:
            return CiResult("gitlab", CI_RUNNING, reason=f"no pipeline for {head[:12]} yet", sha=head)
    if not pipelines:
        return CiResult("gitlab", CI_UNKNOWN, reason=outcome.reason or "no pipeline for the branch", sha=head)
    newest = pipelines[0]
    state = _GITLAB.get(str(newest.get("status")), CI_UNKNOWN)
    tests = await ci_tests.gitlab_tests(db, run, ref, str(newest.get("id") or "")) if head and state in (
        CI_SUCCEEDED, CI_FAILED) else None
    return CiResult("gitlab", state, str(newest.get("web_url") or ""), sha=head, tests=tests)


async def read_ci_status(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> CiResult:
    job = str(params.get("job") or "").strip()
    try:
        if job:
            if params.get("unpinned"):
                return await _jenkins(db, run, job, queue_url=str(params.get("queue_url") or ""),
                                      build_number=str(params.get("build_number") or ""))
            return await _jenkins(db, run, job)
        return await _native(db, run, str(params.get("workflow") or "").strip())
    except Exception as error:  # an unreachable CI is an unknown state, recorded with its reason
        return CiResult("jenkins" if job else "native", CI_UNKNOWN, reason=f"{type(error).__name__}: {error}"[:300],
                        sha=_head(run))


def record_ci(run: WorkflowRun, result: CiResult) -> None:
    context = dict(run.context or {})
    context["ci"] = result.to_dict()
    if result.build and isinstance(context.get("deploy"), dict) and not context["deploy"].get("build_number"):
        context["deploy"] = {**context["deploy"], "build_number": result.build}
    run.context = context
    if result.tests is not None and (result.tests.results or result.tests.unresolved):
        from ..test_runs import record_test_run

        record_test_run(run, {"source": "ci", "all_green": result.state == CI_SUCCEEDED, **result.tests.fields(),
                              "sha": result.sha})


async def ci_status(db: AsyncSession, run: WorkflowRun, params: dict[str, Any]) -> CiResult:
    result = await read_ci_status(db, run, params)
    record_ci(run, result)
    return result


__all__ = ["CI_FAILED", "CI_RUNNING", "CI_SUCCEEDED", "CI_UNKNOWN", "CiResult", "ci_status", "jenkins_tests",
           "read_ci_status", "record_ci"]
