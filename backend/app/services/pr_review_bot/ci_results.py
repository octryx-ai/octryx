"""The reviewed commit's CI results as findings (a red check is a finding).

The bot never runs a repository's tests itself (a stranger's pull request would run on the server, concept §8); it
reads what the repository's own CI reported for the commit it reviewed, when it posts:

- GitHub: commit statuses and check runs (``get_github_commit_checks``);
- GitLab: pipeline jobs and external commit statuses (``get_gitlab_commit_checks``);
- Bitbucket Cloud and Server/Data Center: build statuses (``get_bitbucket_build_statuses``).

The bot's own status (``octryx/review``, Bitbucket key and GitLab name ``octryx-review``) never counts. A failed
check is a **high** finding ``CI<n>`` in the summary table with its link; a check still running is named in the footer
(the incremental review of stage C reads it again). A CI that cannot be read is named in the footer too, never a
failed review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ..workflow_runs.platform.dispatch import dispatch_tool
from ..workflow_runs.platform.repo_ref import parse_repository

CI_FILE = "(CI)"
_OWN = frozenset({"octryx/review", "octryx-review", "octryx review"})
_BITBUCKET_STATES = {"SUCCESSFUL": "success", "FAILED": "failure", "STOPPED": "failure", "INPROGRESS": "pending"}
# The CI tool per provider; GitHub's and GitLab's answer ``checks`` already in one shape, Bitbucket ``statuses``.
CI_TOOLS = {"github": "get_github_commit_checks", "gitlab": "get_gitlab_commit_checks",
            "bitbucket": "get_bitbucket_build_statuses"}
_SHAPED = frozenset({"github", "gitlab"})


@dataclass(slots=True)
class CiResult:
    findings: list[dict[str, Any]] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    unread: str = ""  # why the CI could not be read ('' when it was)


def _checks(provider: str, answer: dict[str, Any]) -> list[dict[str, str]]:
    if provider in _SHAPED:
        return [check for check in answer.get("checks") or [] if isinstance(check, dict)]
    return [{"name": str(item.get("name") or item.get("key") or ""), "state": _BITBUCKET_STATES.get(
        str(item.get("state") or "").upper(), "other"), "url": str(item.get("url") or ""),
        "description": str(item.get("description") or ""), "key": str(item.get("key") or "")}
        for item in answer.get("statuses") or [] if isinstance(item, dict)]


def short(text: str, limit: int = 160) -> str:
    """``text`` within ``limit`` characters, cut at a word boundary with "…" (never in the middle of a word)."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:")
    return f"{cut}…"


def ci_findings(provider: str, answer: dict[str, Any]) -> CiResult:
    """The failed and running checks of one tool answer, the bot's own status left out. Pure."""
    result = CiResult(unread=short(str(answer.get("check_runs_unread") or "")))
    for check in _checks(provider, answer):
        name = str(check.get("name") or "")
        if not name or name.lower() in _OWN or str(check.get("key") or "").lower() in _OWN:
            continue
        if check.get("state") == "pending":
            result.pending.append(name)
        elif check.get("state") == "failure":
            detail = str(check.get("description") or "").strip()
            link = str(check.get("url") or "").strip()
            fix = (f"The CI check '{name}' failed on this commit" + (f": {detail}" if detail else "") + "."
                   + (f" {link}" if link else "") + " Fix what it reports before merging.")
            result.findings.append({"severity": "high", "file": CI_FILE, "line": 1, "fix": fix,
                                    "id": f"CI{len(result.findings) + 1}", "source": "ci"})
    return result


async def read_ci(db: AsyncSession, run: WorkflowRun, commit: str) -> CiResult:
    ref = parse_repository(run.repository)
    if ref is None or ref.provider not in CI_TOOLS or not commit:
        return CiResult(unread="no GitHub, GitLab or Bitbucket repository")
    outcome = await dispatch_tool(db, run, CI_TOOLS[ref.provider], {**ref.args(), "commit": commit},
                                  capability_class="read_only")
    if not outcome.ok:
        return CiResult(unread=short(outcome.reason) or "the CI results could not be read")
    return ci_findings(ref.provider, outcome.result)


__all__ = ["CI_FILE", "CI_TOOLS", "CiResult", "ci_findings", "read_ci"]
