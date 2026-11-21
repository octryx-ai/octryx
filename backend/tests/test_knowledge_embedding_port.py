"""The Embedder port: closed catalog, bounded input, validated vectors, fixed failures.

No real model or provider is needed here: the Bedrock adapter runs against a recording fake
client, and the local adapter is checked up to its artifact gate.
"""

from __future__ import annotations

import json
import re

import pytest
from sqlalchemy import update

from app.models import Project
from app.services.knowledge.embedding.bedrock import COHERE_MAX_TEXTS, BedrockEmbedder
from app.services.knowledge.embedding.catalog import EMBEDDING_SPACES, EmbeddingProvider, embedding_space
from app.services.knowledge.embedding.local import LocalEmbedder
from app.services.knowledge.embedding.port import (
    MAX_BATCH_TEXTS,
    EmbeddingError,
    EmbeddingPurpose,
    EmbeddingState,
    checked_inputs,
    checked_vectors,
)
from app.services.knowledge.embedding.selection import admit_space, embedding_config_from_environment
from tests.knowledge_evidence_seed_support import seed_workspace

TITAN = embedding_space("bedrock_titan2_1024_v1")
COHERE = embedding_space("bedrock_cohere_ml3_1024_v1")
LOCAL = embedding_space("local_mlminilm_384_v1")


def test_every_space_has_a_registry_safe_key() -> None:
    keys = list(EMBEDDING_SPACES)
    assert len(set(keys)) == len(keys)
    for key in keys:
        assert re.fullmatch(r"[a-z0-9_]+", key)
    for space in EMBEDDING_SPACES.values():
        if space.provider is EmbeddingProvider.LOCAL:
            assert space.artifact_revision and all(
                re.fullmatch(r"[0-9a-f]{64}", h) for h in space.artifact_files.values()
            )
        else:
            assert space.data_policy_class


def test_inputs_are_bounded_and_prefixed_per_purpose() -> None:
    assert checked_inputs(TITAN, ["drill"], EmbeddingPurpose.QUERY) == ["drill"]
    with pytest.raises(EmbeddingError) as batch:
        checked_inputs(TITAN, ["x"] * (MAX_BATCH_TEXTS + 1), EmbeddingPurpose.DOCUMENT)
    assert batch.value.state is EmbeddingState.LIMIT_EXCEEDED
    with pytest.raises(EmbeddingError) as blank:
        checked_inputs(TITAN, ["  "], EmbeddingPurpose.DOCUMENT)
    assert blank.value.state is EmbeddingState.CONTRACT_VIOLATION
    with pytest.raises(EmbeddingError) as long:
        checked_inputs(COHERE, ["x" * (COHERE.max_input_chars + 1)], EmbeddingPurpose.DOCUMENT)
    assert long.value.state is EmbeddingState.LIMIT_EXCEEDED


@pytest.mark.parametrize(
    "vectors",
    [[[0.1] * 1023], [[0.1] * 1024, [0.1] * 1024], [[float("nan")] + [0.1] * 1023], [["x"] * 1024], "nope"],
)
def test_a_vector_of_the_wrong_shape_is_a_contract_violation(vectors) -> None:
    with pytest.raises(EmbeddingError) as error:
        checked_vectors(TITAN, vectors, 1)
    assert error.value.state is EmbeddingState.CONTRACT_VIOLATION


class _Body:
    def __init__(self, payload: dict) -> None:
        self._raw = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._raw


class _FakeBedrock:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self._fail = fail

    def invoke_model(self, *, modelId: str, body: str, contentType: str, accept: str):  # noqa: N803 - boto3 casing
        request = json.loads(body)
        self.calls.append({"model": modelId, **request})
        if self._fail is not None:
            raise self._fail
        if "inputText" in request:
            return {"body": _Body({"embedding": [0.5] * request["dimensions"], "inputTextTokenCount": 3})}
        return {"body": _Body({"embeddings": {"float": [[0.25] * 1024 for _ in request["texts"]]}})}


async def test_titan_requests_the_space_dimension_normalized_one_text_at_a_time() -> None:
    client = _FakeBedrock()
    vectors = await BedrockEmbedder(TITAN, client=client).embed(["a", "b"], EmbeddingPurpose.DOCUMENT)
    assert len(vectors) == 2 and len(vectors[0]) == 1024
    assert client.calls == [
        {"model": TITAN.model, "inputText": text, "dimensions": 1024, "normalize": True} for text in ("a", "b")
    ]


async def test_cohere_marks_query_and_document_and_batches_within_its_limit() -> None:
    client = _FakeBedrock()
    embedder = BedrockEmbedder(COHERE, client=client)
    await embedder.embed(["q"], EmbeddingPurpose.QUERY)
    await embedder.embed(["d"] * MAX_BATCH_TEXTS, EmbeddingPurpose.DOCUMENT)
    assert [call["input_type"] for call in client.calls] == ["search_query", "search_document"]
    assert all(len(call["texts"]) <= COHERE_MAX_TEXTS for call in client.calls)


async def test_a_provider_failure_keeps_only_a_fixed_state_and_reason() -> None:
    from botocore.exceptions import ClientError

    leaky = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "arn:aws:iam::123456789012:role/secret-role"}},
        "InvokeModel",
    )
    with pytest.raises(EmbeddingError) as denied:
        await BedrockEmbedder(TITAN, client=_FakeBedrock(fail=leaky)).embed(["a"], EmbeddingPurpose.QUERY)
    assert (denied.value.state, denied.value.reason) == (EmbeddingState.DENIED, "provider_access_denied")
    assert "123456789012" not in str(denied.value) and denied.value.__cause__ is None
    with pytest.raises(EmbeddingError) as other:
        await BedrockEmbedder(TITAN, client=_FakeBedrock(fail=RuntimeError("boom"))).embed(
            ["a"], EmbeddingPurpose.QUERY
        )
    assert (other.value.state, other.value.reason) == (EmbeddingState.UNAVAILABLE, "provider_failed")


async def test_a_local_space_refuses_a_missing_or_altered_artifact(tmp_path) -> None:
    with pytest.raises(EmbeddingError) as missing:
        await LocalEmbedder(LOCAL, model_root=tmp_path).embed(["a"], EmbeddingPurpose.QUERY)
    assert (missing.value.state, missing.value.reason) == (EmbeddingState.NEEDS_CONFIGURATION, "model_artifact_missing")
    artifact = tmp_path / LOCAL.key
    artifact.mkdir()
    for name in LOCAL.artifact_files:
        (artifact / name).write_bytes(b"not the pinned bytes")
    with pytest.raises(EmbeddingError) as altered:
        await LocalEmbedder(LOCAL, model_root=tmp_path).embed(["a"], EmbeddingPurpose.QUERY)
    assert altered.value.reason == "model_artifact_mismatch"


def test_no_space_configured_is_an_explicit_state() -> None:
    with pytest.raises(EmbeddingError) as absent:
        embedding_config_from_environment({})
    assert absent.value.reason == "space_not_configured"
    with pytest.raises(EmbeddingError) as unknown:
        embedding_config_from_environment({"OCTRYX_KNOWLEDGE_EMBEDDING_SPACE": "made_up_v1"})
    assert unknown.value.reason == "space_unknown"


async def test_a_remote_space_is_admitted_only_up_to_its_data_classification(db) -> None:
    workspace_id = await seed_workspace(db)
    await admit_space(db, project_id=workspace_id, space=LOCAL)  # local never leaves the process

    with pytest.raises(EmbeddingError) as unresolved:
        await admit_space(db, project_id=workspace_id, space=TITAN)
    assert unresolved.value.state is EmbeddingState.NEEDS_CONFIGURATION

    for classification, allowed in (("internal", True), ("confidential", False)):
        await db.execute(
            update(Project)
            .where(Project.id == workspace_id)
            .values(config={"data_policy": {"classification": classification}})
        )
        await db.flush()
        if allowed:
            await admit_space(db, project_id=workspace_id, space=TITAN)
        else:
            with pytest.raises(EmbeddingError) as denied:
                await admit_space(db, project_id=workspace_id, space=TITAN)
            assert denied.value.state is EmbeddingState.DENIED
