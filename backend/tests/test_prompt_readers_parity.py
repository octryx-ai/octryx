"""The same turn with different wording gets the same context sections.

Through the real ``prepare_agent_run``, every prompt below gets the same:

- context prompt selection and injection;
- prefetch (nothing is enqueued: no prompt regex warms the cache);
- Engineering Knowledge runtime context (stack, versions, repository);
- corporate identity section;
- repository microagents and knowledge files.

None of these follows prompt wording (context prompt keywords, prefetch ``intent_pattern`` regexes, the
repository named in the prompt, corporate identity keywords, microagent triggers): the probes are negative
controls. The test uses only stable entry points.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.agent.core.context.run_context import prepare_agent_run
from app.agent.engine.messages._engine_message_helpers import _exclude_tool_definitions, _filter_tool_definitions
from app.models import Project, Session, User
from app.services.prefetch.worker import prefetch_worker

CI_MARKER = "CI-GUIDE-MARKER-W26"
PROMPTS = [
    "ping",
    "Create a PowerPoint presentation deck with our corporate branding.",
    "Write a Word document report with citations from the uploaded pdf.",
    "Investigate the deploy issue in acme-orders-access-proxy and check Jira ticket RIVER-123.",
    "Migrate acme-orders-access-proxy to Java 25 and Spring Boot 4.0.3.",
    "what changed from Spring Boot 3 to 4",
    "This older tool result only shows an artifact_id, please inspect it.",
]
class _RunningTask:
    def done(self) -> bool:
        return False


def _write_microagents(root: Path) -> None:
    agents = root / ".agents"
    (agents / "knowledge").mkdir(parents=True, exist_ok=True)
    (agents / "always.md").write_text(
        "---\nname: Always Agent\nalways_include: true\n---\nALWAYS-MICROAGENT\n", encoding="utf-8"
    )
    (agents / "deploy.md").write_text(
        "---\nname: Deploy Agent\ntriggers: [deploy, jira, presentation, spring]\n---\nTRIGGERED-MICROAGENT\n",
        encoding="utf-8",
    )
    (agents / "knowledge" / "release.md").write_text(
        "---\ntitle: Release Notes\ntriggers: [spring, migrate]\ntags: [jira]\n---\nTRIGGERED-KNOWLEDGE\n",
        encoding="utf-8",
    )


@pytest.fixture
def prefetch_jobs(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    jobs: list[Any] = []

    async def record(job: Any) -> int:
        jobs.append(sorted(request.tool_name for request in job.requests))
        return len(job.requests)

    monkeypatch.setattr(prefetch_worker, "_task", _RunningTask())
    monkeypatch.setattr(prefetch_worker, "enqueue", record)
    return jobs


@pytest.fixture
def corp_identity_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    async def default_profile(_db: Any) -> dict[str, Any]:
        return {"name": CI_MARKER, "summary": {}}

    monkeypatch.setattr("app.services.corp_identity_service.get_default_corp_identity_profile", default_profile)


async def _turn_facts(db, *, tmp_path: Path, project: Project, admin: User, prompt: str, metadata: dict, jobs: list):
    session = Session(
        id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="diagnosis", metadata_=metadata
    )
    db.add(session)
    await db.commit()
    jobs.clear()
    prepared = await prepare_agent_run(
        db=db,
        session_id=session.id,
        user_message=prompt,
        user_id=admin.id,
        project_id=project.id,
        agent_type="diagnosis",
        runtime_target_id=None,
        thinking_level="light",
        agent_definition=None,
        parent_session_id=None,
        sub_agent_depth=0,
        workspace_root=str(tmp_path),
        resolve_model_context_cap=lambda *args, **kwargs: asyncio.sleep(0, result=None),
        resolve_control_plane_runtimes_func=lambda *args, **kwargs: asyncio.sleep(0, result=[]),
        filter_tool_definitions=_filter_tool_definitions,
        exclude_tool_definitions=_exclude_tool_definitions,
        trim_messages_to_budget=lambda messages, _budget: messages,
    )
    engineering = prepared.session_metadata.get("engineering_knowledge_runtime_resolution") or {}
    return {
        # A8: the instructions the turn read (key only), bound by scope and the selected workflow.
        "instructions": [item.get("key") for item in prepared.session_metadata.get("instructions") or []],
        "prefetch_jobs": list(jobs),
        "engineering_contract": engineering.get("prompt_contract"),
        "engineering_repository": (engineering.get("repository") or {}).get("name"),
        "engineering_blockers": sorted(item.get("code") for item in engineering.get("blockers") or []),
        "corp_identity": CI_MARKER in prepared.system_prompt,
        "microagents": prepared.repo_microagents_prompt,
        "repo_knowledge": prepared.repo_knowledge_prompt,
    }


async def _project(db, *, name: str) -> tuple[User, Project]:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(
        id=str(uuid.uuid4()),
        name=f"{name}-{uuid.uuid4().hex[:6]}",
        config={"jira_url": "https://jira.example.test", "bitbucket_url": "https://bitbucket.example.test"},
        is_active=True,
    )
    db.add(project)
    await db.commit()
    return admin, project


@pytest.mark.asyncio
async def test_wording_does_not_change_prompts_prefetch_corp_identity_or_microagents(
    db, tmp_path: Path, prefetch_jobs: list, corp_identity_profile: None
) -> None:
    _write_microagents(tmp_path)
    admin, project = await _project(db, name="w26-chat-parity")

    facts = {
        prompt: await _turn_facts(
            db, tmp_path=tmp_path, project=project, admin=admin, prompt=prompt, metadata={}, jobs=prefetch_jobs
        )
        for prompt in PROMPTS
    }

    reference = facts[PROMPTS[0]]
    for prompt, turn in facts.items():
        assert turn == reference, prompt
    assert reference["prefetch_jobs"] == []
    assert reference["corp_identity"] is False
    assert "ALWAYS-MICROAGENT" in reference["microagents"]
    assert "TRIGGERED-MICROAGENT" not in reference["microagents"]
    assert "TRIGGERED-KNOWLEDGE" not in reference["repo_knowledge"]
