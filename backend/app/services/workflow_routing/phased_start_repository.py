"""The repository of a chat's phased start: on the card before Allow, and the run gets it like the Work item dialog.

Without it a chat start whose request names its repository ("Repository owner/repo") ends at once, blocked:
``scm.create_branch`` fails with "the run's repository '' is not github:…/bitbucket:…" whenever the Workspace has
several repository records, because ``definition_of_ready.default_repository`` then finds none.

:func:`repository_choice` resolves the repository in this order:

1. the record the request names (``owner/repo``, or its unique slug);
2. the Workspace's only record with a coding setup;
3. a confirmed Definition of Ready of an existing item (``default_repository``).

Otherwise the card asks for it (``required`` without ``ref``), and the start refuses until one is chosen. A run that
works in a repository (an ``scm.*``, ``workspace.prepare`` or ``pipeline.run`` step) never starts without one.

A record's run reference is ``<provider>:<owner>/<repo>`` (``scm.parse_repository``). A record registered from the
knowledge snapshot takes its provider from its Knowledge source's remote (``bitbucket.org/octryx/kitchen-helper``).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import CodeRepository
from ...models.project.knowledge_source_sync import KnowledgeSourceConnector

_REPOSITORY_STEPS = ("scm.", "workspace.prepare", "pipeline.run")


def _text(value: Any) -> str:
    return str(value or "").strip()


def needs_repository(definition: dict[str, Any]) -> bool:
    configs = [dict(node.get("config") or {}) for node in definition.get("nodes") or [] if isinstance(node, dict)]
    return any(_text(config.get("action") or config.get("tool")).startswith(_REPOSITORY_STEPS) for config in configs)


def _provider_of(source: KnowledgeSourceConnector | None) -> str | None:
    """The SCM provider of a Knowledge git source: its remote's host or path, else its connector key's prefix."""
    from ..workflow_runs.platform.repo_ref import PROVIDERS

    if source is None:
        return None
    scope = source.scope if isinstance(source.scope, dict) else {}
    remote = urlparse(_text(scope.get("remote")).lower())
    for provider in PROVIDERS:
        if provider in remote.netloc or f"/{provider}/" in f"{remote.path}/":
            return provider
    prefix = _text(source.connector_key).lower().split("-", 1)[0]
    return prefix if prefix in PROVIDERS else None


def run_reference(repo: CodeRepository, sources: dict[str, KnowledgeSourceConnector]) -> str | None:
    """``<provider>:<owner>/<repo>`` of a repository record, or ``None`` when no SCM provider is known."""
    from ..workflow_runs.platform.repo_ref import PROVIDERS, parse_repository, record_path

    provider = repo.provider if repo.provider in PROVIDERS else _provider_of(
        sources.get(_text(dict(dict(repo.config_json or {}).get("central_source") or {}).get("connector_id"))))
    ref = f"{provider}:{record_path(repo.name)}" if provider else ""
    return ref if parse_repository(ref) is not None else None


async def repository_options(db: AsyncSession, project_id: str | None) -> list[dict[str, Any]]:
    """The Workspace's active repository records a run can work in: id, name, run reference, coding setup."""
    from ..workflow_runs.platform.repo_ref import record_path

    if not project_id:
        return []
    repos = list((await db.execute(select(CodeRepository).where(
        CodeRepository.project_id == project_id, CodeRepository.is_active.is_(True)).order_by(CodeRepository.name)
    )).scalars())
    ids = {_text(dict(dict(repo.config_json or {}).get("central_source") or {}).get("connector_id")) for repo in repos}
    sources = {row.id: row for row in (await db.execute(select(KnowledgeSourceConnector).where(
        KnowledgeSourceConnector.id.in_(ids - {""})))).scalars()} if ids - {""} else {}
    options = []
    for repo in repos:
        ref = run_reference(repo, sources)
        if ref:
            options.append({"id": repo.id, "name": repo.name, "path": record_path(repo.name), "ref": ref,
                            "coding": bool(dict(repo.config_json or {}).get("coding_setup"))})
    return options


def named_in(message: str, options: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The option the request names: its ``owner/repo`` path, else its slug when exactly one option has it."""
    text = (message or "").lower()
    by_path = [option for option in options if re.search(rf"(?<![\w/-]){re.escape(option['path'])}(?![\w/-])", text)]
    if len(by_path) == 1:
        return by_path[0]
    by_slug = [option for option in options
               if re.search(rf"(?<![\w/-]){re.escape(option['path'].rsplit('/', 1)[-1])}(?![\w/-])", text)]
    return by_slug[0] if len(by_slug) == 1 else None


def _chosen(option: dict[str, Any], source: str) -> dict[str, Any]:
    return {"ref": option["ref"], "name": option["name"], "id": option["id"], "source": source}


async def repository_choice(db: AsyncSession, *, project_id: str | None, message: str, definition: dict[str, Any],
                            item_id: str | None) -> dict[str, Any] | None:
    """The card's repository (see the module docstring); ``None`` for a workflow that works in no repository."""
    from ..workflow_runs.definition_of_ready import default_repository

    if not needs_repository(definition):
        return None
    options = await repository_options(db, project_id)
    listed = [{key: option[key] for key in ("id", "name", "ref")} for option in options]
    named = named_in(message, options)
    coding = [option for option in options if option["coding"]]
    if named is not None:
        chosen = _chosen(named, "request")
    elif len(coding) == 1:
        chosen = _chosen(coding[0], "only_coding_repository")
    else:
        ready = await default_repository(db, item_id, project_id)
        chosen = {"ref": ready, "name": ready, "id": None, "source": "work_item"} if ready else {
            "ref": None, "name": None, "id": None, "source": None}
    return {**chosen, "required": True, "options": listed}


def choose(repository: dict[str, Any], value: str) -> dict[str, Any] | None:
    """The card's repository after the person picked ``value`` (an option's id or reference), or ``None``."""
    option = next((option for option in repository.get("options") or []
                   if _text(value) in (option["id"], option["ref"])), None)
    return {**repository, **_chosen(option, "chosen")} if option is not None else None


def missing_text(repository: dict[str, Any] | None) -> str | None:
    """Why the start cannot run yet, or ``None`` when its repository is known (or it needs none)."""
    if repository is None or repository.get("ref"):
        return None
    names = ", ".join(option["name"] for option in repository.get("options") or [])
    return ("Choose the repository the run works in" + (f" ({names})" if names else
                                                        ": this Workspace has no repository a run can use yet") + ".")


__all__ = ["choose", "missing_text", "named_in", "needs_repository", "repository_choice", "repository_options",
           "run_reference"]
