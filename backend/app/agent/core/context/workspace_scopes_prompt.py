"""The Workspace's connected scopes in the chat prompt: Jira projects, Confluence spaces, code repositories.

Without them a chat prompt names none of the bound scopes: asked for open pull requests the model asks the person
for a ``project_key``, a Jira search runs without a project and misses, and branch commits get mixed up. One line
naming the scopes is enough to avoid all three. So the prompt carries a short block,
built from what the Workspace already knows (no configuration):

- each active named connection with the keys it is bound to (``workspace_routes``, never a config value or secret);
- the Workspace's active repository records with their default branch, and the default repository a run would use
  (``default_repository``: the only one, else none — then the person names it).

Nothing is listed when the Workspace has neither, so a plain Workspace's prompt is unchanged.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....services.prompt_catalog import render_prompt

# What a bound key is, per connector, in the person's words.
_SCOPE_NOUN = {"jira": "project", "confluence": "space", "bitbucket": "repository", "github": "repository",
               "gitlab": "project"}
_CONNECTOR_LABEL = {"jira": "Jira", "confluence": "Confluence", "bitbucket": "Bitbucket", "github": "GitHub",
                    "gitlab": "GitLab"}


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, (list, tuple, set, frozenset)):
        return [text for item in value for text in _strings(item)]
    return []


def repository_spellings(repositories: list[Any]) -> list[str]:
    """The original spellings a Workspace's repository records carry: ``CHEF/kitchen-helper-mini`` from name and clone URL."""
    spellings: list[str] = []
    for repo in repositories:
        spellings.append(str(getattr(repo, "name", "") or ""))
        path = urlsplit(str(getattr(repo, "remote_url", "") or "")).path.removesuffix(".git").strip("/").split("/")
        if len(path) >= 2:
            spellings.append(f"{path[-2]}/{path[-1]}")
    return [text for text in spellings if text]


def original_spelling(key: str, spellings: list[str]) -> str:
    """``key`` as the Workspace spells it elsewhere (``chef/kitchen-helper-mini`` -> ``CHEF/kitchen-helper-mini``), else unchanged.

    The binding stores a canonical lower-case key; a model that copies it into a tool call against a case-sensitive
    server (``project_key: "chef"``) finds nothing and answers wrongly, so the prompt shows the Workspace's spelling."""
    folded = key.casefold()
    for text in spellings:
        if text.strip().casefold() == folded:
            return text.strip()
    if "/" in key:  # each part as spelled anywhere (``CHEF`` of ``CHEF/other-repo``)
        parts = [part for text in spellings for part in text.split("/")]
        return "/".join(original_spelling(part, parts) for part in key.split("/"))
    return key


def connection_lines(connections: list[Any], spellings: list[str] | None = None) -> list[str]:
    """One line per active connection that is bound to keys: ``- Jira (Jira (local)): project CHEF``.

    Keys are shown as the Workspace spells them (repository records, the connection's own settings), never in the
    binding's canonical case: a model copies what it reads, and a case-sensitive server then finds nothing."""
    lines: list[str] = []
    for connection in connections:
        known = [*(spellings or ()), *_strings(getattr(connection, "config", None) or {})]
        keys = sorted(original_spelling(str(key), known) for key in getattr(connection, "bound_scopes", ()) or ())
        if not keys or not getattr(connection, "is_active", True):
            continue
        tool = str(connection.tool_name)
        noun = _SCOPE_NOUN.get(tool, "scope")
        label = _CONNECTOR_LABEL.get(tool, tool)
        lines.append(f"- {label} ({connection.name}): {noun}{'s' if len(keys) > 1 else ''} {', '.join(keys)}")
    return lines


def repository_lines(repositories: list[Any], default_ref: str | None) -> list[str]:
    """One line per repository record; the default one says so."""
    lines: list[str] = []
    for repo in repositories:
        branch = f", default branch {repo.default_branch}" if repo.default_branch else ""
        is_default = bool(default_ref) and default_ref == f"{repo.provider}:{repo.name}"
        lines.append(f"- Repository {repo.name} ({repo.provider}{branch}){' — default' if is_default else ''}")
    return lines


async def workspace_scopes_prompt(db: AsyncSession, project_id: str | None) -> str:
    """The short Workspace-scopes block of the chat prompt, or ``""`` when the Workspace has nothing to name."""
    if not project_id:
        return ""
    from app.services.named_connections.workspace_routes import workspace_routes

    from ....models import CodeRepository
    from ....services.workflow_runs.definition_of_ready import default_repository

    routes = await workspace_routes(db, project_id, secrets=False)
    repositories = list((await db.execute(select(CodeRepository).where(
        CodeRepository.project_id == project_id, CodeRepository.is_active.is_(True)).order_by(CodeRepository.name)
    )).scalars())
    default_ref = await default_repository(db, None, project_id) if repositories else None
    lines = [*connection_lines(list(routes.connections), repository_spellings(repositories)),
             *repository_lines(repositories, default_ref)]
    if not lines:
        return ""
    return render_prompt("system.workspace_scopes", scopes="\n".join(lines))


__all__ = ["connection_lines", "original_spelling", "repository_lines", "repository_spellings", "workspace_scopes_prompt"]
