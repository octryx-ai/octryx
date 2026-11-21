"""Workspace identity, per-workspace database names and source-object references validate their inputs strictly."""

from __future__ import annotations

import re
import uuid

import pytest

from app.services.knowledge.identity.workspace import WorkspaceId
from app.services.knowledge.objects.keys import workspace_object_prefix
from app.services.knowledge.objects.source_object import SourceObjectRef
from app.services.knowledge.retrieval.errors import (
    InvalidRetrievalRequestError,
    InvalidWorkspaceError,
    RetrievalFailureState,
    WorkspaceRequiredError,
)
from tests.knowledge_contracts_support import WS, _SneakyStr, _SubWorkspace


class _SubUUID(uuid.UUID):
    __slots__ = ()


# --- Workspace identity -----------------------------------------------------


def test_workspace_parse_normalizes_canonical_uuid():
    parsed = WorkspaceId.parse(WS.upper())
    assert parsed.canonical == WS
    assert str(parsed) == WS
    assert WorkspaceId.parse(uuid.UUID(WS)) == parsed
    # An existing identity is revalidated into a fresh copy, never shared.
    copy = WorkspaceId.parse(parsed)
    assert copy == parsed and copy is not parsed and copy.value is not parsed.value


@pytest.mark.parametrize("raw", [None, ""])
def test_workspace_missing_is_denied(raw):
    with pytest.raises(WorkspaceRequiredError) as exc_info:
        WorkspaceId.parse(raw)
    assert exc_info.value.state is RetrievalFailureState.DENIED


@pytest.mark.parametrize(
    "raw",
    [
        "*",
        " ",
        f" {WS}",
        f"{{{WS}}}",
        f"urn:uuid:{WS}",
        WS.replace("-", ""),
        "00000000-0000-0000-0000-000000000000",
        "ffffffff-ffff-ffff-ffff-ffffffffffff",
        "default",
        123,
        True,
        [WS],
    ],
)
def test_workspace_rejects_non_canonical_or_reserved_values(raw):
    with pytest.raises(InvalidWorkspaceError) as exc_info:
        WorkspaceId.parse(raw)
    assert exc_info.value.state is RetrievalFailureState.DENIED
    # Fixed message: the rejected value is never echoed.
    assert str(exc_info.value) == InvalidWorkspaceError.default_message


def test_workspace_is_immutable():
    workspace = WorkspaceId.parse(WS)
    with pytest.raises(AttributeError):
        workspace.value = uuid.uuid4()  # type: ignore[misc]


# --- Workspace object partition ------------------------------------------------


def test_workspace_rejects_subclasses_and_revalidates_mutation():
    with pytest.raises(InvalidWorkspaceError):
        WorkspaceId.parse(_SubWorkspace(uuid.UUID(WS)))
    with pytest.raises(InvalidWorkspaceError):
        WorkspaceId(_SubUUID(WS))
    mutated = WorkspaceId.parse(WS)
    object.__setattr__(mutated, "value", uuid.UUID(int=0))
    with pytest.raises(InvalidWorkspaceError):
        WorkspaceId.parse(mutated)
    with pytest.raises(InvalidWorkspaceError):
        workspace_object_prefix(None, mutated)
    with pytest.raises(InvalidWorkspaceError):
        workspace_object_prefix(None, _SubWorkspace(uuid.UUID(WS)))


def test_the_object_partition_is_deterministic_and_safe():
    prefix = workspace_object_prefix(None, WorkspaceId.parse(WS))
    assert prefix == "knowledge/octryx_ws_3f2b8c1e9a4d4e7b8c215d6f7a8b9c0d"
    assert prefix == workspace_object_prefix(None, WorkspaceId.parse(WS.upper()))
    assert re.fullmatch(r"knowledge/octryx_ws_[0-9a-f]{32}", prefix)


def test_the_object_partition_differs_per_workspace():
    other = WorkspaceId.parse(str(uuid.uuid4()))
    assert workspace_object_prefix(None, other) != workspace_object_prefix(None, WorkspaceId.parse(WS))


@pytest.mark.parametrize("raw", [WS, "octryx_ws_x", None, uuid.UUID(WS)])
def test_the_object_partition_requires_a_validated_workspace(raw):
    with pytest.raises(InvalidWorkspaceError):
        workspace_object_prefix(None, raw)  # type: ignore[arg-type]


# --- Source object reference -----------------------------------------------------


def test_source_object_ref_accepts_s3_compatible_reference():
    ref = SourceObjectRef(
        bucket="octryx-knowledge.eu", key="ws/docs/runbook.md", version_id="3HL4kqtJlcpX", content_sha256="a" * 64
    )
    assert ref.key == "ws/docs/runbook.md"
    assert not hasattr(ref, "endpoint") and not hasattr(ref, "credentials")


@pytest.mark.parametrize(
    "bucket", ["ab", "A-bucket", "-bucket", "bucket-", "bu..cket", "bu.-cket", "192.168.1.10", "b" * 64, ""]
)
def test_source_object_ref_rejects_invalid_bucket(bucket):
    with pytest.raises(InvalidRetrievalRequestError):
        SourceObjectRef(bucket=bucket, key="doc.md")


@pytest.mark.parametrize(
    "key", ["", "/abs.md", "a//b.md", "a/../b.md", "./a.md", "a/", "a\nb", "a\x00b", "k" * 1025, "a\ud800b"]
)
def test_source_object_ref_rejects_invalid_key(key):
    with pytest.raises(InvalidRetrievalRequestError):
        SourceObjectRef(bucket="octryx-knowledge", key=key)


@pytest.mark.parametrize(
    "field,value",
    [("version_id", "has space"), ("version_id", ""), ("content_sha256", "A" * 64), ("content_sha256", "a" * 63)],
)
def test_source_object_ref_rejects_invalid_version_and_digest(field, value):
    with pytest.raises(InvalidRetrievalRequestError):
        SourceObjectRef(bucket="octryx-knowledge", key="doc.md", **{field: value})


@pytest.mark.parametrize("field", ["bucket", "key", "version_id", "content_sha256"])
def test_source_object_ref_requires_exact_str_fields(field):
    values = {"bucket": "kb-docs", "key": "a/b.md", "version_id": "v1", "content_sha256": "0" * 64}
    values[field] = _SneakyStr(values[field])
    with pytest.raises(InvalidRetrievalRequestError):
        SourceObjectRef(**values)
