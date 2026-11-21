"""A1 ("what changed from Spring Boot 3 to 4"): turn preparation reads no stack or version from the prompt.

``knowledge_changes`` takes product and versions from its explicit arguments only.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.engineering_knowledge.runtime_prompt_renderer import resolve_engineering_knowledge_runtime_prompt
from app.tools.context import ToolContext
from app.tools.knowledge_evidence.changes import KnowledgeChangesTool

A1_PROMPT = "what changed from Spring Boot 3 to 4"


@pytest.mark.asyncio
async def test_a1_turn_preparation_reads_no_stack_or_version_from_the_prompt(db) -> None:
    # No selected upgrade definition: no Engineering Knowledge section and no inferred target.
    prompt, metadata = await resolve_engineering_knowledge_runtime_prompt(db=db, project_id=None, session_metadata={})
    assert (prompt, metadata) == ("", {})


@pytest.mark.asyncio
async def test_a1_knowledge_changes_takes_product_and_versions_from_explicit_arguments(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    scope = object()

    async def fake_scope(_params: Any, _context: Any) -> object:
        return scope

    async def fake_scoped_changes(_db: Any, *, runtime: Any, scope: Any, product: Any, **options: Any):
        calls.append({"product": product, **options})
        raise RuntimeError("stop after recording the arguments")

    monkeypatch.setattr("app.tools.knowledge_evidence.changes.knowledge_scope", fake_scope)
    monkeypatch.setattr("app.services.knowledge.temporal.scoped_changes.scoped_changes", fake_scoped_changes)
    monkeypatch.setattr("app.tools.knowledge_evidence.changes.get_evidence_runtime", lambda: None)
    context = ToolContext(
        user_id="u",
        project_ids=["p"],
        roles=["admin"],
        session_id="s",
        project_config={"project_id": "p"},
        current_user_message=A1_PROMPT,
        db=db,
    )

    for params in ({"product": "spring-boot", "from_version": "3", "to_version": "4"}, {}):
        with pytest.raises(RuntimeError, match="recording"):
            await KnowledgeChangesTool().execute(params, context)

    explicit, bare = calls
    assert (explicit["product"], explicit["from_version"], explicit["to_version"]) == ("spring-boot", "3", "4")
    # Without arguments nothing is read from the message: product and versions stay unset.
    assert (bare["product"], bare["from_version"], bare["to_version"]) == (None, None, None)


