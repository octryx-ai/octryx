"""Knowledge packages are researched by a governed model, owned by the author, ingested on approval."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.project.knowledge_evidence import KnowledgeRevisionScope, KnowledgeSourceRevisionOrigin
from app.models.project.knowledge_packages import KnowledgePackageDocument
from app.models.project.web_trusted_sources import WebTrustedSource
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ledger.errors import InvalidEvidenceRequestError
from app.services.knowledge.research import package_research
from app.services.knowledge.research import package_sync as sync_module
from app.services.knowledge.research.discovery import Candidate
from app.services.knowledge.research.package_catalog import add_document
from app.services.knowledge.research.package_research import extend_package, research_package
from app.services.knowledge.research.package_sync import sync_package
from app.services.knowledge.sources.web_fetch import FetchedDocument, FetchRefusedError, fetch_public_document
from app.services.web_search.registry import put_source
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace

GUIDE = "https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.0-Migration-Guide"
NOTES = "https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.0-Release-Notes"
BLOG = "https://blog.example.com/spring-boot-4-in-five-minutes"
NOTES_41 = "https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.1-Release-Notes"
NOTES_RC = "https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.0.0-RC1-Release-Notes"


class FakeModel:
    def __init__(self, answers):
        self.answers = list(answers)
        self.usage = type("Usage", (), {"to_dict": lambda self: {"calls": 2}})()

    async def json(self, *, system, user, max_tokens=4096):
        return self.answers.pop(0)


async def _workspace(db, *, trusted: tuple[str, ...] = ("github.com/spring-projects", "docs.spring.io")):
    workspace_id = await seed_workspace(db)
    for pattern in trusted:
        await put_source(db, project_id=workspace_id, pattern=pattern, state="trusted", user_id=None)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    user = await fetch_user(db, user_id)
    return await authorize_workspace(db, current_user=user, workspace_id=workspace_id), user


def _patch(monkeypatch, model, results):
    async def governed(db, *, project_id):
        return model

    async def search(db, project_id, queries, *, hosts, product, policy):
        return [Candidate(url, title, "") for url, title in results], ["fake:ok"]

    async def alive(urls):
        return set(urls)

    monkeypatch.setattr(package_research, "governed_research_model", governed)
    monkeypatch.setattr(package_research, "_search", search)
    monkeypatch.setattr(package_research, "verified", alive)


async def test_research_keeps_only_real_results_and_an_extension_only_adds_new_sources(db, monkeypatch):
    authorized, user = await _workspace(db)
    plan = {"title": "Spring Boot 3.5 to 4.0", "product": "spring-boot", "versions": ["4.0"], "queries": ["q"]}
    selection = {
        "documents": [
            {
                "result": 1,
                "version": "4.0",
                "role": "migration_guide",
                "title": "Migration Guide",
                "rationale": "vendor",
            },
            {"result": 2, "version": "4.0", "role": "release_notes", "title": "Release Notes", "rationale": "vendor"},
            {"result": 9, "version": "4.0", "role": "release_notes", "title": "Invented", "rationale": "x"},
            {"result": 3, "version": None, "role": "blog_post", "title": "Blog", "rationale": "not a role"},
            {"result": 4, "version": "4.0.0-RC1", "role": "release_notes", "title": "RC1", "rationale": "pre-release"},
        ]
    }
    results = [(GUIDE, "Guide"), (NOTES, "Notes"), (BLOG, "Blog"), (NOTES_RC, "RC1")]
    _patch(monkeypatch, FakeModel([plan, selection]), results)
    package = await research_package(db, authorized=authorized, topic="Spring Boot 3.5 to 4.0", created_by=user.id)

    rows = (
        (await db.execute(select(KnowledgePackageDocument).order_by(KnowledgePackageDocument.ordinal))).scalars().all()
    )
    assert package.product == "spring-boot" and [row.url for row in rows] == [GUIDE, NOTES]
    assert package.research["rounds"][0]["queries"] == ["q"]

    more = {
        "documents": [
            {"result": 1, "version": "4.1", "role": "release_notes", "title": "4.1 Notes", "rationale": "asked for"}
        ]
    }
    _patch(monkeypatch, FakeModel([plan, more]), [(GUIDE, "Guide"), (NOTES_41, "4.1 Notes")])
    added = await extend_package(db, authorized=authorized, package=package, instruction="add the 4.1 release notes")

    urls = (
        (await db.execute(select(KnowledgePackageDocument.url).order_by(KnowledgePackageDocument.ordinal)))
        .scalars()
        .all()
    )
    assert added == 1 and urls == [GUIDE, NOTES, NOTES_41] and "4.1" in package.versions


async def test_approval_ingests_exactly_the_accepted_documents_with_product_version_and_link(db, monkeypatch):
    authorized, user = await _workspace(db)
    _patch(
        monkeypatch,
        FakeModel(
            [
                {"title": "Boot 4", "product": "spring-boot", "versions": ["4.0"], "queries": ["q"]},
                {
                    "documents": [
                        {"result": 1, "version": "4.0", "role": "migration_guide", "title": "Guide", "rationale": "r"},
                        {"result": 2, "version": "4.0", "role": "release_notes", "title": "Notes", "rationale": "r"},
                    ]
                },
            ]
        ),
        [(GUIDE, "Guide"), (NOTES, "Notes")],
    )
    package = await research_package(db, authorized=authorized, topic="Boot 4", created_by=user.id)
    guide, notes = (
        (await db.execute(select(KnowledgePackageDocument).order_by(KnowledgePackageDocument.ordinal))).scalars().all()
    )
    guide.state, notes.state = "accepted", "rejected"
    await db.commit()
    with pytest.raises(InvalidEvidenceRequestError):
        await add_document(
            db,
            package,
            url="http://insecure.example.com/x",
            title="x",
            version=None,
            role="reference",
            added_by="admin",
        )
    manual = await add_document(
        db,
        package,
        url="https://docs.spring.io/spring-boot/reference/index.html",
        title="Reference",
        version="4.0",
        role="reference",
        added_by="admin",
    )
    fetched: list[str] = []

    async def fetch(url):
        fetched.append(url)
        return FetchedDocument(url=url, media_type="text/markdown", data=f"# {url}\n\nBody.\n".encode())

    monkeypatch.setattr(sync_module, "fetch_public_document", fetch)
    runtime, _, evidence_index = build_runtime()

    counts = await sync_package(db, runtime=runtime, authorized=authorized, package=package, created_by=user.id)

    assert counts == {"ingested": 2, "failed": 0, "held": 0} and fetched == [GUIDE, manual.url]
    scopes = (await db.execute(select(KnowledgeRevisionScope.products, KnowledgeRevisionScope.version))).all()
    origins = set((await db.execute(select(KnowledgeSourceRevisionOrigin.source_url))).scalars())
    assert all(products == ["spring-boot"] and version == "4.0" for products, version in scopes)
    assert origins == {GUIDE, manual.url}


async def test_an_untrusted_source_becomes_a_proposal_and_its_documents_are_held(db, monkeypatch):
    authorized, user = await _workspace(db, trusted=())
    plan = {"title": "Boot 4", "product": "spring-boot", "versions": ["4.0"], "queries": [], "seed_urls": [GUIDE]}
    selection = {
        "documents": [{"result": 1, "version": "4.0", "role": "migration_guide", "title": "Guide", "rationale": "r"}]
    }
    _patch(monkeypatch, FakeModel([plan, selection]), [])

    async def entry_points(seeds, policy):
        return [(GUIDE, "Migration Guide", [])]

    monkeypatch.setattr(package_research, "entry_points", entry_points)
    package = await research_package(db, authorized=authorized, topic="Boot 4", created_by=user.id)

    proposal = (await db.execute(select(WebTrustedSource))).scalars().one()
    assert (proposal.pattern, proposal.state, proposal.origin, proposal.evidence_url) == (
        "github.com/spring-projects/spring-boot",
        "proposed",
        "agent",
        GUIDE,
    )
    assert package.research["rounds"][0]["source_proposals"] == ["github.com/spring-projects/spring-boot"]
    document = (await db.execute(select(KnowledgePackageDocument))).scalars().one()
    document.state = "accepted"
    await db.commit()

    async def fetch(url):
        return FetchedDocument(url=url, media_type="text/markdown", data=b"# Guide\n\nBody.\n")

    monkeypatch.setattr(sync_module, "fetch_public_document", fetch)
    runtime, _, evidence_index = build_runtime()
    held = await sync_package(db, runtime=runtime, authorized=authorized, package=package, created_by=user.id)
    assert held == {"ingested": 0, "failed": 0, "held": 1}

    proposal.state = "trusted"
    await db.commit()
    counts = await sync_package(db, runtime=runtime, authorized=authorized, package=package, created_by=user.id)
    assert counts == {"ingested": 1, "failed": 0, "held": 0}


async def test_the_fetcher_refuses_anything_but_public_https():
    for url in (
        "http://example.com/doc",
        "https://127.0.0.1/doc",
        "https://user:pw@example.com/doc",
        "https://example.com:8443/doc",
    ):
        with pytest.raises(FetchRefusedError):
            await fetch_public_document(url)
