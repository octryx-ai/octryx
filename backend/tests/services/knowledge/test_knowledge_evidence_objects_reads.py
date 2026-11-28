"""Reads verify the content digest, close the body and stay inside the workspace and bucket, transport failures map to fixed error states without server text, and the boundary touches no filesystem path."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from app.services.knowledge.objects import (
    MAX_OBJECT_BYTES,
    KnowledgeObjectError,
    KnowledgeObjectIntegrityError,
    KnowledgeObjectNotConfiguredError,
    KnowledgeObjectNotFoundError,
    KnowledgeObjectOperation,
    KnowledgeObjectTooLargeError,
    KnowledgeObjectUnauthorizedError,
    KnowledgeObjectUnavailableError,
)
from app.services.knowledge.objects import errors as object_errors
from app.services.knowledge.objects import store as object_store_module
from tests.services.knowledge.knowledge_evidence_objects_support import PAYLOAD, _workspace
from tests.support.knowledge_evidence_s3_support import FakeS3Client, object_store


def _imported_modules(tree: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def _called_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Attribute):
                names.add(target.attr)
    return names


async def test_read_verifies_the_content_digest():
    client = FakeS3Client()
    store = object_store(client)
    workspace = _workspace()
    stored = await store.put_if_absent(workspace, PAYLOAD)

    assert await store.get_verified(workspace, stored.ref) == PAYLOAD

    client.objects[(stored.ref.bucket, stored.ref.key)] = b"tampered bytes"
    with pytest.raises(KnowledgeObjectIntegrityError):
        await store.get_verified(workspace, stored.ref)


async def test_a_read_always_closes_the_response_body():
    client = FakeS3Client()
    store = object_store(client)
    workspace = _workspace()
    stored = await store.put_if_absent(workspace, PAYLOAD)

    await store.get_verified(workspace, stored.ref)
    assert [body.closed for body in client.bodies] == [True]

    # A digest mismatch refuses after the read: the body must still be closed.
    client.objects[(stored.ref.bucket, stored.ref.key)] = b"tampered bytes"
    with pytest.raises(KnowledgeObjectIntegrityError):
        await store.get_verified(workspace, stored.ref)
    assert [body.closed for body in client.bodies] == [True, True]

    # And when the object is over the bound, which refuses after the read too.
    client.objects[(stored.ref.bucket, stored.ref.key)] = b"x" * (MAX_OBJECT_BYTES + 1)
    with pytest.raises(KnowledgeObjectTooLargeError):
        await store.get_verified(workspace, stored.ref)
    assert [body.closed for body in client.bodies] == [True, True, True]


async def test_another_workspaces_object_reads_as_absent():
    client = FakeS3Client()
    owner, other = _workspace(), _workspace()
    stored = await object_store(client).put_if_absent(owner, PAYLOAD)

    # The bytes exist, but not inside the caller's partition.
    with pytest.raises(KnowledgeObjectNotFoundError):
        await object_store(client).get_verified(other, stored.ref)
    assert "GetObject" not in client.calls


async def test_a_ref_recorded_under_another_bucket_reads_the_configured_bucket_only():
    from dataclasses import replace

    client = FakeS3Client()
    owner, other = _workspace(), _workspace()
    stored = await object_store(client).put_if_absent(owner, PAYLOAD)
    migrated = replace(stored.ref, bucket="octryx-knowledge")

    assert await object_store(client).get_verified(owner, migrated) == PAYLOAD
    # Partition isolation is unchanged by the recorded bucket name.
    with pytest.raises(KnowledgeObjectNotFoundError):
        await object_store(client).get_verified(other, migrated)
    # And an object absent from the configured bucket stays absent, whatever the row recorded.
    client.objects.clear()
    with pytest.raises(KnowledgeObjectNotFoundError):
        await object_store(client).get_verified(owner, migrated)


async def test_transport_failures_map_to_fixed_states():
    for flag, expected in (
        ("unauthorized", KnowledgeObjectUnauthorizedError),
        ("unavailable", KnowledgeObjectUnavailableError),
        ("absent_bucket", KnowledgeObjectNotConfiguredError),
    ):
        client = FakeS3Client(**{flag: True})
        with pytest.raises(expected):
            await object_store(client).put_if_absent(_workspace(), PAYLOAD)


async def test_errors_carry_no_server_text_and_no_chained_cause():
    client = FakeS3Client(unauthorized=True)
    with pytest.raises(KnowledgeObjectUnauthorizedError) as caught:
        await object_store(client).put_if_absent(_workspace(), PAYLOAD)
    error = caught.value
    assert str(error) == type(error).default_message
    assert "server text" not in str(error)
    # No botocore exception is chained: it would reference the signed request.
    assert error.__cause__ is None and error.__context__ is None


def test_every_object_state_has_exactly_one_error_class():
    classes = [
        value
        for value in vars(object_errors).values()
        if isinstance(value, type) and issubclass(value, KnowledgeObjectError) and value is not KnowledgeObjectError
    ]
    states = [cls.state for cls in classes]
    assert len(states) == len(set(states))
    assert set(states) == set(object_errors.KnowledgeObjectState) - {object_errors.KnowledgeObjectState.READY}


def test_object_errors_accept_no_free_text():
    with pytest.raises(TypeError):
        KnowledgeObjectNotFoundError("bucket=leaked")
    assert KnowledgeObjectNotFoundError(KnowledgeObjectOperation.GET_OBJECT).operation is (
        KnowledgeObjectOperation.GET_OBJECT
    )


def test_the_object_boundary_contains_no_filesystem_path():
    package = Path(inspect.getfile(object_store_module)).parent
    sources = sorted(package.glob("*.py"))
    assert sources, "object package sources not found"
    forbidden_modules = {"pathlib", "os", "os.path", "tempfile", "shutil", "io", "glob"}
    forbidden_calls = {"open", "mkdir", "write_bytes", "read_bytes", "write_text", "read_text", "unlink"}
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = _imported_modules(tree)
        assert not modules & forbidden_modules, f"{path.name} imports {modules & forbidden_modules}"
        # And it must not reach for the shared artifact-store settings, whose
        # default backend is "filesystem", nor for application settings at all.
        assert not any("artifact_store" in module for module in modules), path.name
        calls = _called_names(tree)
        assert not calls & forbidden_calls, f"{path.name} calls {calls & forbidden_calls}"
        assert "get_settings" not in calls, path.name
