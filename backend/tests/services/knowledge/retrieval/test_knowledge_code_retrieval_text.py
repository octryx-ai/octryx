"""A code span is found by its file, symbol and identifier words, and quotes only its own lines (A3-green)."""

from __future__ import annotations

from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.code.retrieval_text import MAX_WORDS, code_retrieval_text, identifier_words
from app.services.knowledge.embedding.catalog import embedding_space
from app.services.knowledge.embedding.port import EmbeddingPurpose, EmbeddingRuntime
from app.services.knowledge.ingestion.code_ingest import ingest_code_source
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.retrieval.evidence import retrieve_workspace_evidence
from app.services.knowledge.retrieval.lexical_ranking import TermFetchEvidence, rank_candidates
from app.services.knowledge.retrieval.lexical_terms import query_terms, word_forms
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.knowledge_evidence_text_support import ConceptEmbedder

PATH = "src/main/java/demo/owner/OwnerController.java"
JAVA = """package demo.owner;

import org.springframework.cache.annotation.EnableCaching;

@EnableCaching
class OwnerController {

    @GetMapping("/owners/new")
    public String initCreationForm() {
        return VIEWS_OWNER_FORM;
    }
}
"""


class RecordingEmbedder(ConceptEmbedder):
    def __init__(self, space) -> None:
        super().__init__(space)
        self.documents: list[str] = []

    async def embed(self, texts, purpose):
        if purpose is EmbeddingPurpose.DOCUMENT:
            self.documents.extend(texts)
        return await super().embed(texts, purpose)


def test_the_retrieval_text_names_the_file_the_symbol_and_the_identifier_words() -> None:
    assert identifier_words("initCreationForm") == ["init", "creation", "form"]
    assert identifier_words("HTTPServer") == ["http", "server"]
    assert identifier_words("vet_specialties") == ["vet", "specialties"]

    text = code_retrieval_text("@EnableCaching\nclass A {}", path=PATH, section_path=("OwnerController", "init"))

    header, words, lines = text.split("\n", 2)
    assert header == f"{PATH} § OwnerController.init" and lines == "@EnableCaching\nclass A {}"
    assert {"owner", "controller", "enable", "caching"} <= set(words.split())
    assert code_retrieval_text("x", path=PATH, section_path=()) == code_retrieval_text("x", path=PATH, section_path=())
    many = " ".join(f"camelWord{i}Part" for i in range(400))
    assert len(code_retrieval_text(many, path=PATH, section_path=()).split("\n")[1].split()) <= MAX_WORDS


async def test_a_code_span_is_indexed_by_its_words_and_quotes_only_its_lines(db) -> None:
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    space = embedding_space("local_mlminilm_384_v1")
    embedder = RecordingEmbedder(space)
    runtime, _, evidence_index = build_runtime(embedding=EmbeddingRuntime(space=space, embedder=embedder))
    database = authorized.workspace.canonical
    await ingest_code_source(
        db, runtime=runtime, authorized=authorized, source_key="owner-controller", display_title=PATH,
        data=JAVA.encode(), created_by=user_id, source_url=f"https://github.com/o/r/blob/{'a' * 40}/{PATH}",
        language="java",
    )
    projector = EvidenceProjector(runtime)
    while await projector.project_once(db, worker_id="test") is not None:
        pass

    result = await retrieve_workspace_evidence(db, runtime=runtime, authorized=authorized, query_text="creation")

    (hit,) = result.evidence
    lines = JAVA.split("\n")
    assert hit.text == "\n".join(lines[4:11]) and hit.source_url.endswith("#L5-L11")
    body = evidence_index.workspace_records(database)[hit.evidence_key]["body_text"]
    assert body.startswith(f"{PATH} § OwnerController\n") and body.endswith(hit.text)
    assert any(document.startswith(f"{PATH} § OwnerController\n@EnableCaching") for document in embedder.documents)


def test_ranking_weighs_the_selective_term_and_matches_singulars() -> None:
    candidates = {
        "k1": "pet visit owner pet visit owner exist",
        "k2": "@Entity class Pet {} private Set<Visit> visits;",
        "k3": "messages pet visit owner type new",
    }
    terms = query_terms("Which entities exist, and how are Pet and Visit related?")
    evidence = {
        "entities": TermFetchEvidence(records=2, saturated=False),
        "exist": TermFetchEvidence(records=40, saturated=False),
        "pet": TermFetchEvidence(records=64, saturated=True),
        "visit": TermFetchEvidence(records=64, saturated=True),
    }

    ranked = [key for key, _ in rank_candidates(candidates, terms, evidence, cap=64)]

    assert ranked[0] == "k2"
    assert word_forms("entities") >= {"entity"} and word_forms("class") == {"class"}
