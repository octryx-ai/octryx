"""The run's repository on its provider: the reference, its record, the branch name, reviewers and commit trailers."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import CodeRepository, WorkflowRun
from ....models.runtime.secure_work import WorkItem
from ...source_control.branch_naming import render_branch
from .dispatch import FAILED, ToolOutcome
from .pr_reviewers import REQUESTER_IS_AUTHOR, PrReviewers, requester_reviewer

PROVIDERS = ("github", "gitlab", "bitbucket")


# Git's empty tree: the base of a run on a repository without any commit (the whole first commit is its change).
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
REPOSITORY_EMPTY_KEY = "repository_empty"
TOOLS: dict[str, dict[str, str]] = {
    "github": {"branch": "create_github_branch", "prepare": "prepare_github_repository",
               "push": "commit_and_push_github_repository_branch", "pr": "create_github_pull_request",
               "get_pr": "get_github_pull_request"},
    "gitlab": {"branch": "create_gitlab_branch", "prepare": "prepare_gitlab_repository",
               "push": "commit_and_push_gitlab_repository_branch", "pr": "create_gitlab_merge_request",
               "get_pr": "get_gitlab_merge_request"},
    "bitbucket": {"branch": "create_bitbucket_branch", "prepare": "prepare_bitbucket_repository",
                  "push": "commit_and_push_repository_branch", "pr": "create_bitbucket_pull_request",
                  "get_pr": "get_bitbucket_pull_request"},
}
MAX_SLUG = 40


@dataclass(frozen=True, slots=True)
class RepoRef:
    provider: str
    path: str

    def args(self) -> dict[str, Any]:
        if self.provider == "github":
            return {"repository": self.path}
        if self.provider == "gitlab":
            return {"project": self.path}
        project_key, _, slug = self.path.partition("/")
        return {"project_key": project_key, "repo_slug": slug}

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]


def parse_repository(value: str | None) -> RepoRef | None:
    provider, _, path = str(value or "").strip().partition(":")
    provider, path = provider.lower(), path.strip().strip("/")
    if provider not in PROVIDERS or path.count("/") < 1:
        return None
    return RepoRef(provider, path)


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:MAX_SLUG].strip("-") or "change"


async def _record(db: AsyncSession, run: WorkflowRun, ref: RepoRef) -> CodeRepository | None:
    if not run.project_id:
        return None
    rows = (await db.execute(select(CodeRepository).where(
        CodeRepository.project_id == run.project_id, CodeRepository.provider.in_((ref.provider, SNAPSHOT_PROVIDER)),
        CodeRepository.is_active.is_(True),
    ))).scalars().all()
    wanted = {ref.path.lower(), ref.name.lower()}
    matches = [row for row in rows if record_path(row.name) in wanted]
    # a Workspace repository registered from the knowledge snapshot (provider ``knowledge_snapshot``,
    # named ``bitbucket/projects/<key>/repos/<slug>``) carries the coding setup; the provider's own record wins.
    return next((row for row in matches if row.provider == ref.provider), matches[0] if matches else None)


SNAPSHOT_PROVIDER = "knowledge_snapshot"
_SERVER_NAME = re.compile(r"(?:^|/)projects/([^/]+)/repos/([^/]+)$")


def record_path(name: str | None) -> str:
    # Bitbucket Server record names differ from the run's <owner>/<repo>; without this the coding setup is never found.
    text = str(name or "").strip().strip("/").lower()
    match = _SERVER_NAME.search(text)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    head, _, rest = text.partition("/")
    return rest if head in PROVIDERS and rest.count("/") >= 1 else text


def _setup(record: CodeRepository | None) -> dict[str, Any]:
    stored = dict(record.config_json or {}).get("coding_setup") if record is not None else None
    return dict(stored) if isinstance(stored, dict) else {}


def ai_trailers(run: WorkflowRun, item: WorkItem | None, used_models: list[str] | None = None) -> str:
    context = dict(run.context or {})
    target = context.get("runtime_target") if isinstance(context.get("runtime_target"), dict) else {}
    models = [_trailer_value(name) for name in used_models or []]
    models = list(dict.fromkeys(name for name in models if name)) or [
        _trailer_value(str(target.get("model") or context.get("model") or "unknown"))]
    key = re.sub(r"[^A-Za-z0-9._-]", "", work_key(run, item) or str(run.id or ""))[:40]
    return "\n".join([f"AI-Generated-By-octryx: {model}" for model in models]
                     + ([f"Octryx-Run: {key}"] if key else []))


def _trailer_value(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._:/-]", "", str(model or ""))[:80]


async def run_models(db: AsyncSession, run: WorkflowRun) -> list[str]:
    from ....models import TurnTrace, UsageEvent, WorkflowRunSession

    sessions = select(WorkflowRunSession.session_id).where(WorkflowRunSession.run_id == run.id)
    rows = []
    for table in (TurnTrace, UsageEvent):
        rows += (await db.execute(select(table.model, table.created_at).where(
            table.session_id.in_(sessions), table.model.is_not(None), table.model != ""))).all()
    seen = sorted(rows, key=lambda row: (row[1] is None, row[1] or 0))
    return list(dict.fromkeys(str(model).strip() for model, _ in seen if str(model).strip()))


def work_key(run: WorkflowRun, item: WorkItem | None) -> str:
    key = str(run.ticket_key or "").strip()
    if not key and item is not None and str(item.source_type or "").lower() == "platform":
        key = str(item.source_key or "").strip()
    return key


async def branch_name(db: AsyncSession, run: WorkflowRun, ref: RepoRef, branch_type: str) -> str:
    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    key = work_key(run, item)
    rule = str(_setup(await _record(db, run, ref)).get("branch_naming_rule") or "")
    return render_branch(rule, branch_type=branch_type, key=key, slug=slugify(item.title if item is not None
                                                                                else run.title))


def _no_repository(run: WorkflowRun) -> ToolOutcome:
    return ToolOutcome(FAILED, reason=f"the run's repository '{run.repository or ''}' is not "
                                      "github:<owner>/<repo>, gitlab:<group>/<project> or bitbucket:<key>/<slug>")


def _not_found(outcome: ToolOutcome) -> bool:
    text = f"{outcome.reason} {outcome.result}".lower()
    return "404" in text or "not found" in text or "does not exist" in text


async def reviewers_for(db: AsyncSession, run: WorkflowRun, ref: RepoRef) -> PrReviewers:
    requester, platform_key, unresolved = await requester_reviewer(db, run, ref)
    is_author = unresolved == REQUESTER_IS_AUTHOR
    owners = [str(name) for name in _setup(await _record(db, run, ref)).get("owners") or [] if str(name).strip()]
    return PrReviewers(requester, tuple(name for name in dict.fromkeys(owners) if name != requester), platform_key,
                       "" if is_author else unresolved, is_author)
