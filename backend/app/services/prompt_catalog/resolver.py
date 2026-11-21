"""The one prompt resolver: Workspace > workflow > global published > seed.

``resolve_prompt_set`` reads every published version of the three scopes that apply
to a turn in one query and picks, per key, the most specific one. A key with no
published version at any scope resolves to its code seed, recorded as source
``seed``. A published body that no longer fits its key's placeholder contract (for
example after a release narrowed the variables) is not skipped in favour of a less
specific scope: the key is refused when it is rendered.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.runtime.prompt_template import (
    PROMPT_SCOPE_GLOBAL,
    PROMPT_SCOPE_WORKFLOW,
    PROMPT_SCOPE_WORKSPACE,
    PromptTemplate,
    PromptTemplateVersion,
)
from .contract import (
    REASON_PLACEHOLDER_UNKNOWN,
    PromptKeySpec,
    PromptTemplateUnavailableError,
    prompt_digest,
    unknown_placeholders,
)
from .prompt_set import SOURCE_SEED, PromptSet, ResolvedPrompt, frozen_prompts
from .registry import prompt_key_registry
from .scopes import scope_key

# A workflow's own text (its owner's) sits between the global and the Workspace's.
_PRECEDENCE = {PROMPT_SCOPE_GLOBAL: 1, PROMPT_SCOPE_WORKFLOW: 2, PROMPT_SCOPE_WORKSPACE: 3}


def seed_prompt(spec: PromptKeySpec) -> ResolvedPrompt:
    return ResolvedPrompt(
        key=spec.key,
        body=spec.seed,
        version=0,
        digest=prompt_digest(spec.seed),
        source=SOURCE_SEED,
        literal=spec.literal,
    )


@lru_cache(maxsize=1)
def _seed_prompts() -> Mapping[str, ResolvedPrompt]:
    """Every key at its seed, computed once (the registry is fixed for the process)."""
    return frozen_prompts({key: seed_prompt(spec) for key, spec in prompt_key_registry().items()})


def is_shipped_seed(prompt: ResolvedPrompt) -> bool:
    """Whether ``prompt`` is the unmodified seed this release ships for its key (a published version with the
    same body included); any other body is an administrator's text."""
    seed = _seed_prompts().get(prompt.key)
    return seed is not None and prompt.digest == seed.digest


@lru_cache(maxsize=1)
def _seed_digests() -> frozenset[str]:
    return frozenset(prompt.digest for prompt in _seed_prompts().values())


def shipped_seed_text(text: str) -> bool:
    """Whether ``text`` is exactly the body of a seed this release ships (by content hash): the only text the
    model-call content checks skip (``content_security.model_call``)."""
    return bool(text) and prompt_digest(text) in _seed_digests()


def seed_prompt_set() -> PromptSet:
    """Every key at its seed: for code that runs outside a turn and for tests."""
    return PromptSet(prompts=_seed_prompts(), scope={"type": "seed"})


def turn_scope_keys(workspace_id: str | None, workflow_key: str | None = None) -> list[str]:
    keys = [scope_key(PROMPT_SCOPE_GLOBAL, None)]
    if workflow_key:
        keys.append(scope_key(PROMPT_SCOPE_WORKFLOW, workflow_key))
    if workspace_id:
        keys.append(scope_key(PROMPT_SCOPE_WORKSPACE, workspace_id))
    return keys


async def resolve_prompt_set(
    db: AsyncSession,
    *,
    workspace_id: str | None,
    workflow_key: str | None = None,
) -> PromptSet:
    registry = prompt_key_registry()
    rows = (
        await db.execute(
            select(
                PromptTemplate.key,
                PromptTemplate.scope_type,
                PromptTemplate.scope_id,
                PromptTemplateVersion.version,
                PromptTemplateVersion.body,
                PromptTemplateVersion.digest,
            )
            .join(PromptTemplateVersion, PromptTemplateVersion.template_id == PromptTemplate.id)
            .where(
                PromptTemplate.scope_key.in_(turn_scope_keys(workspace_id, workflow_key)),
                PromptTemplateVersion.state == "published",
            )
        )
    ).all()
    winners: dict[str, tuple[int, ResolvedPrompt]] = {}
    for row in rows:
        if row.key not in registry:
            continue
        rank = _PRECEDENCE[row.scope_type]
        current = winners.get(row.key)
        if current is not None and current[0] >= rank:
            continue
        winners[row.key] = (
            rank,
            ResolvedPrompt(
                key=row.key,
                body=row.body,
                version=int(row.version),
                digest=row.digest,
                source=row.scope_type,
                scope_id=row.scope_id,
                literal=registry[row.key].literal,
            ),
        )
    prompts: dict[str, ResolvedPrompt] = dict(_seed_prompts())
    refusals: dict[str, PromptTemplateUnavailableError] = {}
    for key, (_rank, resolved) in winners.items():
        spec = registry[key]
        unknown = () if spec.literal else unknown_placeholders(resolved.body, spec.placeholders)
        if unknown:
            refusals[key] = PromptTemplateUnavailableError(key, REASON_PLACEHOLDER_UNKNOWN, names=unknown)
            continue
        prompts[key] = resolved
    return PromptSet(
        prompts=frozen_prompts(prompts),
        refusals=refusals,
        scope={"workspace_id": workspace_id or None, **({"workflow_key": workflow_key} if workflow_key else {})},
    )


__all__ = [
    "is_shipped_seed",
    "resolve_prompt_set",
    "seed_prompt",
    "seed_prompt_set",
    "shipped_seed_text",
    "turn_scope_keys",
]
