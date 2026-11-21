"""Fixtures for the structured knowledge graph tests: a synthetic manual, seeded ledger rows.

The manual spans below are a self-written guide for a fictional product (the "Demo Shop Server Guide" and
the "Demo Shop Console" requirements chapter) in the shapes Docling produces for a PDF manual: leaf-only
section paths, ``cell | cell`` table rows, a header-less continuation span after a page break, captions
in the table span and a merged ``Tom- cat My- SQL`` header. ``seed_parsed_revision`` writes a projected
current revision with spans and locators directly, the state the Docling parse step leaves.
"""

from __future__ import annotations

import hashlib
import uuid

from app.models.project.knowledge_evidence import (
    REVISION_STATE_PROJECTED,
    REVISION_STATE_SUPERSEDED,
    KnowledgeEvidenceSource,
    KnowledgeEvidenceSpan,
    KnowledgeSourceHead,
    KnowledgeSourceRevision,
)
from app.models.project.knowledge_parsing import KnowledgeSpanLocator
from app.services.knowledge.ingestion.spans import derive_evidence_key
from app.services.knowledge.structured.facts import SpanInput


def span(ordinal, text, kind="text", page=1, section=(), line_start=None, line_end=None) -> SpanInput:
    return SpanInput(ordinal, text, kind, page, page, tuple(section), line_start, line_end)


SERVER_MANUAL = [
    span(1, "Demo Shop Server Guide", section=["Demo Shop Server Guide"]),
    span(2, "General Information\n\nDemo Shop Server processes the orders of the shop.", page=7,
         section=["General Information"]),
    span(3, "2.1 Deployment Overview\n\nSee Database Settings (page 118) for the connection.", page=7,
         section=["2.1 Deployment Overview"]),
    span(4, "Server Setup\n\nThe server is configured in conf/app.ini.", page=31, section=["Server Setup"]),
    span(5, "6.3.2 Database Settings\n\nThe database settings are defined in a [Database?] section of "
            "conf/app.ini.", page=118, section=["6.3.2 Database Settings"]),
    span(6, "[Database?] Parameter | Default | Description\nEngine | <mandatory> | Database engine. Possible "
            "values are PostgreSQL, MySQL and H2.\nUrl | <mandatory> | JDBC URL of the order database.",
         kind="table", page=118, section=["6.3.2 Database Settings"]),
    span(7, "Ϫ Caution\n\nFor a log of every slow query, refer to QueryLogging (page 47).",
         page=119, section=["Ϫ Caution"]),
    span(8, "6.3.3 Cache Settings\n\nDemo Shop Server can keep data in an external Redis cache (see "
            "RedisCacheProvider (page 156)). See section 6.3.2 for databases.", page=124,
         section=["6.3.3 Cache Settings"]),
    span(9, "[Cache?] Parameter | Default | Description\nHosts | <mandatory> | Comma-separated list of cache "
            "host names.\nConnectTimeout | 60000 | Connect timeout in milliseconds.\nRequestTimeout | 60000 | "
            "Timeout in milliseconds for one cache request.", kind="table", page=125,
         section=["6.3.3 Cache Settings"]),
    span(10, "continues on next page\n\nTable 31 – continued from previous page", page=125,
         section=["6.3.3 Cache Settings"]),
    span(11, "RetryInterval | 5 | Time in milliseconds between two request attempts. RetryInterval "
             "must be smaller than RequestTimeout.\n |  | Values far below the timeout work best.", kind="table",
         page=126, section=["6.3.3 Cache Settings"]),
    span(12, "6.4 Providers\n\nProviders keep cached values.", page=150, section=["6.4 Providers"]),
    span(13, "6.4.1 Cache providers\n\nThe MemoryCacheProvider keeps values in memory.", page=150,
         section=["6.4.1 Cache providers"]),
    span(14, "RedisCacheProvider\n\nThe RedisCacheProvider keeps values in Redis.", page=156,
         section=["RedisCacheProvider"]),
    span(15, "Configuration\n\nThe provider is configured in its own section.", page=156, section=["Configuration"]),
    span(16, "Parameter | Default | Description\nMaxEntries | 1 | Number of entries kept per key.\nEntry"
             "Lifetime | 0 | Lifetime of an entry in seconds.", kind="table", page=157, section=["Configuration"]),
    span(17, "1. Without TLS\n\nStart without TLS.", page=158, section=["1. Without TLS"]),
]

CONSOLE_MANUAL = [
    span(1, "Demo Shop Console\n\nAdministration guide.", page=1, section=["Demo Shop Console"]),
    span(2, "3.2 System Requirements\n\nThe supported platforms follow.", page=48,
         section=["3.2 System Requirements"]),
    span(3, "Demo Shop Console System Requirements\n\nSystem requirements for Demo Shop Console\n\n"
            "Demo Shop Con-sole | Java SE | Jakarta EE | Tom- cat My- SQL | Post-greSQL | Ka- fka\n"
            "3.1 | 21 | 11 | 10.1.20 8.4 | Post-greSQL 16-17 | 3.6- 3.8\n"
            "2.9 | 17, 21 | 10 | 10.1.20 8.0 | Post-greSQL 15-16 | 3.6\n"
            "2.8 | 17 | 10 | 10.1.18 | Post-greSQL 15-16 | 3.4- 3.6",
         kind="table", page=48, section=["3.2 System Requirements"]),
    span(4, "Demo Shop Console | MySQL 8.4\n2.9-3.1 |", kind="table", page=49,
         section=["MySQL replication setup"]),
]


async def seed_parsed_revision(
    db,
    project_id: str,
    *,
    source_key: str,
    title: str,
    spans: list[SpanInput],
    media_type: str = "application/pdf",
    parser: str = "docling-serve",
    source_id: str | None = None,
    revision_ordinal: int = 1,
) -> tuple[str, str]:
    """A projected, current revision with these spans and locators; returns ``(source_id, revision_id)``."""
    if source_id is None:
        source = KnowledgeEvidenceSource(project_id=project_id, source_key=source_key, display_title=title)
        db.add(source)
        await db.flush()
        source_id = source.id
    else:
        head = await db.get(KnowledgeSourceHead, source_id)
        previous = await db.get(KnowledgeSourceRevision, head.current_revision_id)
        previous.state = REVISION_STATE_SUPERSEDED
    revision_id = str(uuid.uuid4())
    digest = hashlib.sha256(f"{source_key}:{revision_ordinal}".encode()).hexdigest()
    db.add(
        KnowledgeSourceRevision(
            id=revision_id, source_id=source_id, project_id=project_id, revision_ordinal=revision_ordinal,
            content_sha256=digest, byte_size=1, media_type=media_type, object_bucket="octryx-knowledge",
            object_key=f"test/{digest}", parser_name=parser, parser_version="1", parser_sandbox="none",
            state=REVISION_STATE_PROJECTED, span_count=len(spans),
        )
    )
    await db.flush()
    position = 0
    for item in spans:
        db.add(
            KnowledgeEvidenceSpan(
                revision_id=revision_id, project_id=project_id, span_ordinal=item.ordinal,
                evidence_key=derive_evidence_key(revision_id, item.ordinal), char_start=position,
                char_end=position + len(item.text), text=item.text,
                citation=f"{title} (rev {revision_ordinal}, p. {item.page_start})",
            )
        )
        position += len(item.text) + 1
        db.add(
            KnowledgeSpanLocator(
                revision_id=revision_id, span_ordinal=item.ordinal, project_id=project_id, kind=item.kind or "text",
                page_start=item.page_start, page_end=item.page_end, section_path=list(item.section_path),
                line_start=item.line_start, line_end=item.line_end,
            )
        )
    head = await db.get(KnowledgeSourceHead, source_id)
    if head is None:
        db.add(KnowledgeSourceHead(source_id=source_id, project_id=project_id, wanted_revision_id=revision_id,
                                   current_revision_id=revision_id))
    else:
        head.wanted_revision_id = head.current_revision_id = revision_id
    await db.commit()
    return source_id, revision_id


async def seed_config_repository(db, runtime, authorized, *, connector_key: str, repo: str,
                                 files: dict[str, str], commit: str = "a" * 40) -> dict[str, str]:
    """A ``git_repository`` connector whose files are ingested as code and indexed; returns path -> revision."""
    from app.models.project.knowledge_code_files import KnowledgeCodeFile, KnowledgeCodeFileBlob
    from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
    from app.services.knowledge.code.repository_paths import path_digest
    from app.services.knowledge.ingestion.code_ingest import ingest_code_source
    from app.services.knowledge.projection.projector import EvidenceProjector

    connector = KnowledgeSourceConnector(project_id=authorized.project_id, connector_key=connector_key,
                                         kind="git_repository", scope={"display_name": repo}, products=[],
                                         cursor={})
    db.add(connector)
    await db.flush()
    revisions = {}
    for path, text in files.items():
        digest = path_digest(path)
        ingested = await ingest_code_source(
            db, runtime=runtime, authorized=authorized, source_key=f"git_repository.{connector_key}.{digest[:40]}",
            display_title=f"{repo}:{path}", data=text.encode(), created_by=None,
            source_url=f"https://git.example.com/{repo}/blob/{commit}/{path}", path=path,
        )
        blob = hashlib.sha1(text.encode()).hexdigest()
        db.add(KnowledgeCodeFile(project_id=authorized.project_id, connector_id=connector.id, path=path,
                                 path_digest=digest, blob_sha=blob, commit_sha=commit, last_seen_commit=commit,
                                 source_id=ingested.source_id, revision_id=ingested.revision_id, elements=[],
                                 element_count=0))
        db.add(KnowledgeCodeFileBlob(project_id=authorized.project_id, connector_id=connector.id,
                                     path_digest=digest, path=path, blob_sha=blob, first_commit=commit,
                                     source_id=ingested.source_id, revision_id=ingested.revision_id))
        revisions[path] = ingested.revision_id
    await db.commit()
    while await EvidenceProjector(runtime).project_once(db, worker_id="test") is not None:
        pass
    return revisions
