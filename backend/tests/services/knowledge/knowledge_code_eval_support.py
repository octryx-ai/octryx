"""The code-question eval: spring-petclinic at its pinned commit, ingested through the real Source Sync and asked
through the same retrieval as the REST ``knowledge_search``."""

from __future__ import annotations

import ipaddress
import pathlib
import tarfile
from dataclasses import dataclass

import httpx

from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.retrieval.hybrid import hybrid_workspace_evidence
from app.services.knowledge.retrieval.locator import evidence_locator
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.service import configure_connector
from app.services.knowledge.sources.sync.service_run import run_connector
from tests.code_eval import answers, questions, repos
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace

OWNER, REPO = "spring-projects", "spring-petclinic"
SHA = "b26f235250627a235a2974a22f2317dbef27338d"
ARCHIVE = pathlib.Path(__file__).parents[2] / "fixtures" / "knowledge_code" / "spring-petclinic-b26f2352.tar.gz"
SEARCH_LIMIT = 8  # Bounded lexical-only baseline; the live hybrid check uses 16.


def archive_tree() -> frozenset[str]:
    with tarfile.open(ARCHIVE, mode="r:gz") as tar:
        return frozenset(
            member.name.split("/", 1)[1] for member in tar.getmembers() if member.isfile() and "/" in member.name
        )


class ArchiveGitHub:
    def __init__(self) -> None:
        self.archive = ARCHIVE.read_bytes()

    def handler(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if request.method != "GET":
            return httpx.Response(405)
        if host == "api.github.com" and path == f"/repos/{OWNER}/{REPO}/commits/{SHA}":
            return httpx.Response(200, text=SHA)
        if host == "codeload.github.com" and path == f"/{OWNER}/{REPO}/tar.gz/{SHA}":
            return httpx.Response(200, content=self.archive)
        return httpx.Response(404)


def public_dns(monkeypatch) -> None:
    async def _resolve(hostname: str, port: int | None):
        return {ipaddress.ip_address("203.0.113.10")}

    async def _no_allowlist(connection: str) -> frozenset[str]:
        return frozenset()

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _resolve)
    monkeypatch.setattr("app.services.outbound_egress.target_check._private_host_keys", _no_allowlist)


@dataclass
class IngestedRepository:
    authorized: object
    runtime: object
    report: dict


async def ingest_petclinic(db, *, max_runs: int = 10) -> IngestedRepository:
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    runtime, _, evidence_index = build_runtime()
    config = validate_config(
        connector_key="a3-spring-petclinic",
        kind="git_repository",
        fetch_mode="remote_git",
        repository_url=f"https://github.com/{OWNER}/{REPO}",
        ref=SHA,
        max_items_per_run=500,
    )
    row = await configure_connector(db, authorized=authorized, config=config, actor_id=user_id)
    transport = httpx.MockTransport(ArchiveGitHub().handler)
    for _ in range(max_runs):
        current = await db.get(KnowledgeSourceConnector, row.id)
        run = await run_connector(
            db, runtime=runtime, authorized=authorized, row=current, actor_id=user_id, transport=transport
        )
        if run.state != "budget_exhausted":
            break
    assert run.state == "completed", (run.state, run.reason)
    projector = EvidenceProjector(runtime)
    for _ in range(20000):
        if await projector.project_once(db, worker_id="eval") is None:
            break
    else:  # pragma: no cover - a projection that never drains is a product bug
        raise AssertionError("the projection did not drain")
    return IngestedRepository(authorized=authorized, runtime=runtime, report=dict(run.report))


async def search_payload(db, ingested: IngestedRepository, query: str, limit: int = SEARCH_LIMIT) -> dict:
    fused = await hybrid_workspace_evidence(
        db, runtime=ingested.runtime, authorized=ingested.authorized, query_text=query, limit=limit
    )
    return {
        "mode_states": dict(fused.mode_states),
        "evidence": [
            {"text": hit.evidence.text, "source_url": hit.evidence.source_url, **evidence_locator(hit.evidence)}
            for hit in fused.evidence
        ],
    }


@dataclass(frozen=True)
class QuestionScore:
    key: str
    ok: bool
    facts_total: int
    facts_missing: tuple[str, ...]
    grounded: bool
    fact: str


async def evaluate(db, ingested: IngestedRepository) -> list[QuestionScore]:
    tree = archive_tree()
    scores: list[QuestionScore] = []
    for question in questions.QUESTIONS:
        payload = await search_payload(db, ingested, question.text)
        verdict = answers.judge_search(question, payload, repos.PETCLINIC, tree)
        text = "\n".join(str(hit.get("text") or "") for hit in payload["evidence"])
        missing = tuple(answers._missing(question.facts, text))
        grounded = any(
            str(hit.get("source_url") or "").split("#", 1)[0].endswith("/" + path)
            for hit in payload["evidence"]
            for path in question.files
        )
        scores.append(QuestionScore(question.key, verdict.ok, len(question.facts), missing, grounded, verdict.fact))
    return scores


def summary(scores: list[QuestionScore]) -> str:
    passed = sum(score.ok for score in scores)
    facts = sum(score.facts_total for score in scores)
    found = facts - sum(len(score.facts_missing) for score in scores)
    lines = [f"questions {passed}/{len(scores)}, facts {found}/{facts}"]
    lines += [f"FAIL {score.key}: {score.fact}" for score in scores if not score.ok]
    return "\n".join(lines)


__all__ = [
    "ARCHIVE",
    "SHA",
    "ArchiveGitHub",
    "IngestedRepository",
    "QuestionScore",
    "archive_tree",
    "evaluate",
    "ingest_petclinic",
    "public_dns",
    "search_payload",
    "summary",
]
