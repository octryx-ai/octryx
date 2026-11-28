"""``list_jenkins_builds``: the recent builds of the alert target's Jenkins jobs, read-only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from ..services.workflow_checks.evidence_families import (
    EMPTY,
    OK,
    REFUSED,
    UNAVAILABLE,
    evidence_envelope,
    with_envelope,
)
from ..time_utils import utc_now_aware
from .alert_scope import AlertScope, parse_rfc3339, query_window, rfc3339, run_alert_scope
from .context import ToolContext

MAX_LIMIT = 20
DEFAULT_LIMIT = 10
DEFAULT_SPAN = timedelta(hours=24)
JOB_OUT_OF_SCOPE = "job_out_of_scope"
JENKINS_NOT_CONFIGURED = "jenkins_not_configured"


def _limit(value: Any) -> int:
    try:
        limit = int(value) if value is not None else DEFAULT_LIMIT
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))


def _envelope(status: str, scope: AlertScope | None, window: dict | None, count: int, reason: str = "") -> dict:
    return evidence_envelope("ci_deploy", status, target_id=scope.target_id if scope else None,
                             namespace=scope.namespace if scope else None, window=window, count=count, reason=reason)


async def _run_or_workspace(context: ToolContext) -> Any | None:
    from ..services.workflow_runs.records import active_run_for_session

    run = await active_run_for_session(context.db, context.session_id) if context.db is not None else None
    if run is not None:
        return run
    project_id = str(context.project_config.get("project_id") or (context.project_ids or [""])[0] or "")
    return SimpleNamespace(project_id=project_id) if project_id else None


async def _allowed_jobs(context: ToolContext, scope: AlertScope | None, run: Any) -> tuple[str, ...]:
    if scope is not None and scope.jenkins_jobs:
        return scope.jenkins_jobs
    from ..services.workflow_runs.platform.deploy import deploy_job

    job = await deploy_job(context.db, run) if run is not None and context.db is not None else ""
    return (job,) if job else ()


def _build_time(build: dict[str, Any]) -> datetime | None:
    stamp = build.get("timestamp")
    if type(stamp) is not int or stamp <= 0:
        return None
    return datetime.fromtimestamp(stamp / 1000, tz=UTC)


class ListJenkinsBuilds:
    name = "list_jenkins_builds"
    description = "List the recent builds of the alert target's Jenkins job in the alert window (read-only)"

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        scope = await run_alert_scope(context)
        job = str(params.get("job") or "").strip()
        run = await _run_or_workspace(context)
        allowed = await _allowed_jobs(context, scope, run)
        if not job and len(allowed) == 1:
            job = allowed[0]
        if not job or job not in allowed:
            return with_envelope({"error": JOB_OUT_OF_SCOPE, "code": JOB_OUT_OF_SCOPE, "job": job or None,
                                  "allowed_jobs": list(allowed)},
                                 _envelope(REFUSED, scope, scope.window() if scope else None, 0, JOB_OUT_OF_SCOPE))
        since = params.get("since")
        since_time = since if parse_rfc3339(since) is not None else None  # ``since`` is a time or a duration
        bounds = query_window({"start": since_time, "end": params.get("until"),
                               "since": None if since_time else since}, scope, now=utc_now_aware(),
                              default_span=DEFAULT_SPAN)
        if isinstance(bounds, str):
            return with_envelope({"error": bounds, "code": bounds, "job": job},
                                 _envelope(REFUSED, scope, scope.window() if scope else None, 0, bounds))
        start, end = bounds
        window = {"start": rfc3339(start), "end": rfc3339(end)}
        limit = _limit(params.get("limit"))

        from ..services.workflow_runs.platform.deploy import jenkins_client

        client = await jenkins_client(context.db, run) if run is not None and context.db is not None else None
        if client is None:
            return with_envelope({"error": JENKINS_NOT_CONFIGURED, "code": JENKINS_NOT_CONFIGURED, "job": job},
                                 _envelope(UNAVAILABLE, scope, window, 0, JENKINS_NOT_CONFIGURED))
        try:
            # Jenkins lists newest first; read a bounded page and keep the builds inside the window.
            listed = await client.list_builds(job, limit=100)
        except Exception as error:  # an unreachable or failing CI is unavailable evidence, never data
            code = f"jenkins_unavailable: {type(error).__name__}"
            return with_envelope({"error": code, "code": "jenkins_unavailable", "job": job},
                                 _envelope(UNAVAILABLE, scope, window, 0, code))
        builds = []
        for build in listed:
            moment = _build_time(build)
            if moment is None or not (start <= moment <= end):
                continue
            builds.append({"number": build.get("build_number"), "status": build.get("status"),
                           "result": build.get("result"), "building": bool(build.get("building")),
                           "timestamp": rfc3339(moment), "duration_ms": build.get("duration_ms"),
                           "commit": build.get("commit") or None, "url": build.get("build_url")})
            if len(builds) >= limit:
                break
        if params.get("include_tests") is True:
            for build in builds:
                build["tests"] = await _test_summary(client, job, build["number"])
        return with_envelope({"job": job, "start": window["start"], "end": window["end"], "limit": limit,
                              "count": len(builds), "builds": builds},
                             _envelope(OK if builds else EMPTY, scope, window, len(builds)))


async def _test_summary(client: Any, job: str, number: Any) -> dict[str, Any]:
    try:
        report = await client.get_test_report(job, number)
    except Exception as error:  # a build without a test report (or a failing read) has no summary
        return {"available": False, "reason": type(error).__name__}
    return {"available": True, "total": report.get("total_count"), "failed": report.get("fail_count"),
            "skipped": report.get("skip_count")}


__all__ = ["JOB_OUT_OF_SCOPE", "ListJenkinsBuilds"]
