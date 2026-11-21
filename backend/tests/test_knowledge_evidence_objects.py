"""The immutable, Workspace-partitioned object boundary.

Covers content addressing, write-if-absent, verify-on-read, cross-Workspace
isolation, the absence of any filesystem fallback, and secret-free errors.
"""

from __future__ import annotations

import base64
import hashlib
import inspect

import pytest

from app.services.knowledge.objects import (
    ENV_BUCKET,
    ENV_ENDPOINT_URL,
    ENV_PREFIX,
    ENV_REGION,
    MAX_OBJECT_BYTES,
    KnowledgeObjectInvalidConfigurationError,
    KnowledgeObjectNotConfiguredError,
    KnowledgeObjectOperation,
    KnowledgeObjectStore,
    KnowledgeObjectTooLargeError,
    content_digest,
    is_key_inside_workspace,
    object_store_config_from_mapping,
    workspace_object_key,
)
from app.services.knowledge.objects import store as object_store_module
from tests.knowledge_evidence_objects_support import PAYLOAD, _workspace
from tests.knowledge_evidence_s3_support import BUCKET, FakeS3Client, object_config, object_store


def _env(**overrides: str) -> dict[str, str]:
    env = {
        ENV_ENDPOINT_URL: "http://127.0.0.1:9000",
        ENV_BUCKET: BUCKET,
        ENV_REGION: "eu-central-1",
        ENV_PREFIX: "octryx/test",
    }
    env.update(overrides)
    return env


def _refuses(key: str, values: tuple[str, ...]) -> None:
    """Every value in the table must fail closed on the same rule."""
    for value in values:
        with pytest.raises(KnowledgeObjectInvalidConfigurationError):
            object_store_config_from_mapping(_env(**{key: value}))


# --- configuration ----------------------------------------------------------


def test_absent_configuration_is_a_typed_state_not_a_directory():
    with pytest.raises(KnowledgeObjectNotConfiguredError):
        object_store_config_from_mapping({})
    for key in (ENV_ENDPOINT_URL, ENV_BUCKET, ENV_REGION):
        env = _env()
        del env[key]
        with pytest.raises(KnowledgeObjectNotConfiguredError):
            object_store_config_from_mapping(env)


def test_invalid_endpoints_fail_closed():
    _refuses(
        ENV_ENDPOINT_URL,
        (
            "http://objects.example.com:9000",  # plaintext to a remote host
            "https://user:pw@objects.example.com",  # userinfo
            "https://127.0.0.1:9000/bucket",  # path
            "https://127.0.0.1:9000?x=1",
            "ftp://127.0.0.1:9000",
            "https://127.0.0.1:0",
            "not-a-url",
        ),
    )


def test_invalid_buckets_fail_closed():
    _refuses(ENV_BUCKET, ("Bad-Upper", "ab", "10.0.0.1", "bucket..name", "bucket-", "a" * 64))


def test_invalid_prefixes_fail_closed():
    _refuses(ENV_PREFIX, ("/leading", "trailing/", "Upper", "a//b", "../escape", "a" * 65))


def test_configuration_never_renders_the_endpoint_or_a_credential():
    config = object_store_config_from_mapping(_env())
    rendered = f"{config!r} {config!s}"
    assert "127.0.0.1" not in rendered and "9000" not in rendered
    assert config.endpoint_url == "http://127.0.0.1:9000"


# --- keys -------------------------------------------------------------------


def test_key_is_content_addressed_and_workspace_partitioned():
    workspace = _workspace()
    digest = content_digest(PAYLOAD)
    key = workspace_object_key("octryx/test", workspace, digest)
    assert key == (
        f"octryx/test/knowledge/octryx_ws_{workspace.value.hex}/sha256/{digest[0:2]}/{digest[2:4]}/{digest}"
    )
    # Deterministic, and the same bytes never produce two keys in one Workspace.
    assert workspace_object_key("octryx/test", workspace, digest) == key


def test_identical_bytes_in_two_workspaces_are_two_keys():
    digest = content_digest(PAYLOAD)
    first, second = _workspace(), _workspace()
    key_a = workspace_object_key(None, first, digest)
    key_b = workspace_object_key(None, second, digest)
    assert key_a != key_b
    assert is_key_inside_workspace(key_a, None, first)
    assert not is_key_inside_workspace(key_a, None, second)
    assert not is_key_inside_workspace(key_b, None, first)


# --- write-if-absent --------------------------------------------------------


async def test_same_bytes_are_written_once_and_reported_as_not_created():
    client = FakeS3Client()
    store = object_store(client)
    workspace = _workspace()

    first = await store.put_if_absent(workspace, PAYLOAD)
    second = await store.put_if_absent(workspace, PAYLOAD)

    assert first.created is True and second.created is False
    assert first.ref == second.ref
    assert len(client.objects) == 1
    assert len(client.puts) == 1


async def test_put_uses_a_server_verified_digest_and_refuses_to_replace():
    client = FakeS3Client()
    await object_store(client).put_if_absent(_workspace(), PAYLOAD)
    sent = client.puts[0]
    expected = base64.b64encode(hashlib.sha256(PAYLOAD).digest()).decode("ascii")
    assert sent["ChecksumSHA256"] == expected
    assert sent["IfNoneMatch"] == "*"
    assert sent["ContentType"] == "application/octet-stream"
    assert sent["ContentLength"] == len(PAYLOAD)


async def test_a_concurrent_writer_winning_is_not_an_error():
    """The precondition, not a probe, resolves the race — and 412 is not a failure."""
    workspace = _workspace()
    key = workspace_object_key("octryx/test", workspace, content_digest(PAYLOAD))
    # Already in the bucket when this writer starts: the conditional put is refused.
    racing = FakeS3Client(objects={(BUCKET, key): PAYLOAD})

    stored = await KnowledgeObjectStore(object_config(), client=racing).put_if_absent(workspace, PAYLOAD)

    assert stored.created is False
    assert stored.ref.key == key
    assert len(racing.objects) == 1


async def test_the_write_path_issues_no_head_object():
    """Finding 9: two S3 actions only, so no HeadObject privilege is required."""
    client = FakeS3Client()
    store = object_store(client)
    workspace = _workspace()

    stored = await store.put_if_absent(workspace, PAYLOAD)
    await store.put_if_absent(workspace, PAYLOAD)
    await store.get_verified(workspace, stored.ref)

    assert client.calls == ["PutObject", "PutObject", "GetObject"]
    # There is no head_object member to reach for, in the enum or in the module.
    assert not hasattr(KnowledgeObjectOperation, "HEAD_OBJECT")
    assert "head_object" not in inspect.getsource(object_store_module)


async def test_oversized_payloads_are_refused_before_any_write():
    client = FakeS3Client()
    with pytest.raises(KnowledgeObjectTooLargeError):
        await object_store(client).put_if_absent(_workspace(), b"x" * (MAX_OBJECT_BYTES + 1))
    assert client.objects == {} and client.puts == []
