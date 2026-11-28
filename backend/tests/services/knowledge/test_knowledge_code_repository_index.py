"""The code index of a git_repository source: one writer for both fetch modes."""

from __future__ import annotations

import pytest

from app.models.project.knowledge_source_sync import CONNECTOR_KIND_GIT_REPOSITORY, KnowledgeSourceConnector
from app.services.knowledge.code.repository_index import mark_seen, retire_unseen, upsert_file
from app.services.knowledge.code.repository_reads import indexed_blobs, load_repository_index
from app.services.knowledge.ledger.errors import EvidenceLedgerContractError
from tests.knowledge_evidence_seed_support import seed_workspace

C1 = "1" * 40
C2 = "2" * 40
POM_BLOB = "a" * 40
APP_BLOB = "b" * 40
POM = "<project>\n  <properties>\n    <java.version>17</java.version>\n  </properties>\n</project>\n"
APP = "import javax.annotation.PostConstruct;\n\n@JsonComponent\nclass App {}\n"


async def _connector(db) -> tuple[str, str]:
    workspace_id = await seed_workspace(db)
    row = KnowledgeSourceConnector(
        project_id=workspace_id, connector_key="repo-0123456789ab", kind=CONNECTOR_KIND_GIT_REPOSITORY,
        scope={"fetch_mode": "local_snapshot"}, products=[], cursor={},
    )
    db.add(row)
    await db.flush()
    return workspace_id, row.id


async def test_index_is_incremental_by_blob_and_answers_elements_at_the_head(db):
    workspace_id, connector_id = await _connector(db)

    def write(path, blob, commit, text):
        return upsert_file(
            db, project_id=workspace_id, connector_id=connector_id, path=path, blob_sha=blob, commit_sha=commit,
            language="java", source_id=None, revision_id=None, text=text,
        )

    pom = await write("pom.xml", POM_BLOB, C1, POM)
    app = await write("src/main/java/App.java", APP_BLOB, C1, APP)
    assert (pom.changed, pom.element_count, app.element_count) == (True, 1, 2)
    assert (await write("logo.png", "c" * 40, C1, None)).element_count == 0

    assert await indexed_blobs(db, connector_id=connector_id, paths=["pom.xml", "new.txt"]) == {"pom.xml": POM_BLOB}
    assert (await write("pom.xml", POM_BLOB, C2, POM)).changed is False
    assert await mark_seen(db, connector_id=connector_id, commit_sha=C2, paths=["logo.png"]) == 1
    retired = await retire_unseen(db, connector_id=connector_id, head_commit=C2)
    assert [path for path, _ in retired] == ["src/main/java/App.java"]

    index = await load_repository_index(db, connector_id=connector_id, head_commit=C2)
    assert index.file_count == 2 and not index.truncated
    assert [(e.kind, e.value, e.path, e.line, e.detail) for e in index.elements] == [
        ("build_property", "java.version", "pom.xml", 3, "17")
    ]


@pytest.mark.parametrize("path", ["/etc/passwd", "../x", "a//b", "a/./b", "a\\b", "a\nb", ""])
async def test_index_refuses_unsafe_paths(db, path):
    workspace_id, connector_id = await _connector(db)
    with pytest.raises(EvidenceLedgerContractError):
        await upsert_file(
            db, project_id=workspace_id, connector_id=connector_id, path=path, blob_sha=POM_BLOB, commit_sha=C1,
            language=None, source_id=None, revision_id=None, text=POM,
        )


async def test_index_refuses_a_non_sha1_blob_or_commit(db):
    workspace_id, connector_id = await _connector(db)
    for blob, commit in (("HEAD", C1), (POM_BLOB, "main")):
        with pytest.raises(EvidenceLedgerContractError):
            await upsert_file(
                db, project_id=workspace_id, connector_id=connector_id, path="pom.xml", blob_sha=blob,
                commit_sha=commit, language=None, source_id=None, revision_id=None, text=POM,
            )
