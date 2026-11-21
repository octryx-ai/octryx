"""What the run card and a run row tell beyond the run's state: the findings it went on with, why the requester is
not the pull request's reviewer, and a triage's follow-up that did not start."""

from __future__ import annotations

from typing import Any

from ...models import WorkflowRun


def open_findings_view(run: WorkflowRun) -> list[dict[str, Any]]:
    """The findings the run went on with (``context.open_findings``, written by the decisions gate), high first, in
    one shape for the run page: severity, file, line, summary, fix."""
    from .auto_accept import _SEVERITY_ORDER, OPEN_FINDINGS_KEY

    items = [dict(item) for item in dict(run.context or {}).get(OPEN_FINDINGS_KEY) or [] if isinstance(item, dict)]
    items.sort(key=lambda item: _SEVERITY_ORDER.get(str(item.get("severity") or "").lower(), 3))
    return [{"severity": str(item.get("severity") or "").lower(), "file": item.get("file") or None,
             "line": item.get("line") or None,
             "summary": str(item.get("summary") or item.get("title") or item.get("reason") or ""),
             "fix": str(item.get("fix") or "")} for item in items]


_PROVIDER_LABELS = {"github": "GitHub", "gitlab": "GitLab", "bitbucket": "Bitbucket"}
REVIEWER_NOTICE = ("You are this pull request's author on {provider} (the connection signs in as you), so you are not "
                   "set as its reviewer: please review and merge it yourself. The run waits for the merge.")
REVIEWER_REFUSED_NOTICE = ("{provider} did not accept you as this pull request's reviewer (most likely you are its "
                           "author through the connection's account): please review and merge it yourself. The run "
                           "waits for the merge.")


REQUESTER_UNRESOLVED_NOTICE = ("Your {account} account is not linked, so you were not added as this pull request's "
                               "reviewer: please review and merge it yourself. The run waits for the merge. Link your "
                               "account to be added as reviewer (Profile → Linked accounts).")


def reviewer_notice(run: WorkflowRun) -> dict[str, str] | None:
    """What the requester does when the run could not make them the pull request's reviewer; ``None`` otherwise."""
    from ..linked_accounts.contract import PLATFORMS

    pr = dict(run.pull_request or {})
    if not pr.get("reviewer_skipped"):
        return None
    reason = str(pr["reviewer_skipped"])
    provider = _PROVIDER_LABELS.get(str(pr.get("provider") or ""), "the SCM")
    if reason == "requester_unresolved":
        platform_key = str(pr.get("requester_platform") or "")
        account = PLATFORMS[platform_key].label if platform_key in PLATFORMS else provider
        return {"reason": reason, "url": str(pr.get("url") or ""), "link_account": platform_key,
                "text": _waiting(run, REQUESTER_UNRESOLVED_NOTICE.format(account=account))}
    notice = REVIEWER_REFUSED_NOTICE if reason == "reviewer_refused" else REVIEWER_NOTICE
    return {"reason": reason, "url": str(pr.get("url") or ""), "text": _waiting(run, notice.format(provider=provider))}


WAITS_FOR_MERGE = " The run waits for the merge."


def _waiting(run: WorkflowRun, text: str) -> str:
    """A finished run waits for nothing (e.g. a workflow that ends after opening the pull request; the
    card must not say the run waits for the merge)."""
    from .states import ACTIVE_STATUSES

    return text if run.status in ACTIVE_STATUSES else text.replace(WAITS_FOR_MERGE, "")


def follow_up_failed(run: Any) -> dict[str, Any] | None:
    """A triage whose follow-up workflow did not start (``triage_routing``, state ``failed``): its workflow, code and
    message, which a work item's runs show (otherwise the failure was silent). The run card reads
    ``routing``."""
    routing = dict(dict(run.context or {}).get("routing") or {})
    if routing.get("state") != "failed":
        return None
    return {key: routing.get(key) for key in ("workflow_key", "code", "message")}
