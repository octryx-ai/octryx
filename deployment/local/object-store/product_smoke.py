"""Live S3 protocol acceptance for the Knowledge object boundary.

Drives the real ``KnowledgeObjectStore`` from
``backend/app/services/knowledge/objects`` against the pinned local
S3-compatible runtime in this directory. Nothing about the boundary is
reimplemented here: the product builds its own boto3 client, derives its own
keys, and maps its own error states, and this script only asserts the outcomes.

What it proves against a real server rather than a double:

1. ``PutObject`` carrying ``ChecksumSHA256`` *and* ``IfNoneMatch: "*"`` in one
   request is accepted, and the server validates the checksum;
2. the same content address a second time is refused with ``412`` and the
   product reports ``created=False`` without ever issuing a ``HeadObject``;
3. a verified read returns exactly the stored bytes;
4. Workspace partitioning: identical bytes in two Workspaces are two objects,
   and a foreign or out-of-bucket reference answers ``not_found`` locally,
   without a request;
5. an absent object answers ``not_found``, a mismatch between stored bytes and
   the content address answers ``integrity_violation``;
6. an absent bucket answers ``needs_configuration``;
7. a refused grant, a wrong secret and an unknown access key all answer
   ``unauthorized``;
8. every request of the store is path-style, signed, and goes to the configured
   loopback endpoint, and the only operations it ever puts on the wire are
   ``PutObject`` and ``GetObject``;
9. the operator-owned reconciliation capability lists exactly one
   Workspace's key prefix, never the bucket; reports the content address, size and
   write time of each object; pages deterministically; deletes one key and refuses a
   foreign one without a request; and its identity — which holds no ``Read`` grant —
   cannot read Workspace bytes at all.

Run it through ``./fixture.sh``, which starts the runtime, generates the
test-only credentials and cleans everything up afterwards.

Boundaries: no credential, object body, authorization header or server error
body is printed. Output is fixed text plus product state names. No ``.env`` file
and no application settings are loaded.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import boto3
from fixture_client import FixtureAdmin, FixtureError
from fixture_contract import (
    ABSENT_BUCKET,
    ADDRESSED,
    ADMIN_IDENTITY,
    BUCKET,
    CLIENT_IDENTITY,
    DENIED_IDENTITY,
    HOST,
    PLANTED,
    PREFIX,
    REGION,
    STORED,
    UNRELATED_BUCKET,
    UNSTORED,
    WORKSPACE_1,
    WORKSPACE_2,
    SmokeError,
    is_within,
    neutralize_ambient_aws,
    port_from_environment,
    product_config_mapping,
    read_identities,
    report_pass,
)
from retention_smoke import run_reconciliation
from wire_observer import ALLOWED_OPERATIONS, WireObserver

_SCRIPT = Path(__file__).resolve()
_CHECKOUT = _SCRIPT.parents[3]
_BACKEND = _CHECKOUT / "backend"
_PRODUCT_PACKAGE = _BACKEND / "app" / "services" / "knowledge" / "objects"


def _load_product():
    """Import the product package from this checkout only (no settings, no .env)."""
    if not (_PRODUCT_PACKAGE / "__init__.py").is_file():
        raise SmokeError("product import: backend package not found in this checkout")
    if "app" in sys.modules:
        raise SmokeError("product import: an 'app' package is already loaded")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(_BACKEND))
    try:
        import app.services.knowledge as knowledge
        import app.services.knowledge.objects as objects
    except ImportError as error:
        # A missing module name is a fixed identifier, never secret data.
        missing = error.name if isinstance(error.name, str) else ""
        if not re.fullmatch(r"[A-Za-z0-9_.]{1,100}", missing):
            missing = "unknown"
        raise SmokeError(
            f"product import: failed on {missing} (use the backend virtualenv, Python 3.11+)"
        ) from None
    origin = Path(objects.__file__).resolve()
    if not is_within(origin, _PRODUCT_PACKAGE.resolve()):
        raise SmokeError("product import: package does not come from this checkout")
    # The boundary must still own exactly these actions: two for the immutable store and
    # two for the operator-owned maintenance capability, plus configuration.
    operations = {member.value for member in objects.KnowledgeObjectOperation}
    if operations != {"configuration", "put_object", "get_object", "list_objects", "delete_object"}:
        raise SmokeError("product import: the operation taxonomy changed; update this smoke")
    # The two capabilities must stay separate classes: the store may never grow a delete.
    forbidden = ("delete_one", "list_workspace", "delete_object", "list_objects_v2")
    if any(hasattr(objects.KnowledgeObjectStore, name) for name in forbidden):
        raise SmokeError("product import: the immutable store gained a maintenance operation")
    if any(hasattr(objects.KnowledgeObjectMaintenance, name) for name in ("get_verified", "put_if_absent")):
        raise SmokeError("product import: the maintenance capability gained a content operation")
    report_pass("product import: Knowledge object package from this checkout")
    return knowledge, objects


@dataclass(frozen=True, slots=True)
class SmokeContext:
    """Everything one acceptance phase needs, resolved once."""

    knowledge: object
    objects: object
    observer: WireObserver
    admin: FixtureAdmin
    secrets: Mapping[str, str]
    port: int

    @property
    def endpoint_host(self) -> str:
        return f"{HOST}:{self.port}"

    def store(self, bucket: str, access_key_id: str, secret_access_key: str):
        """Build a real ``KnowledgeObjectStore`` for one credential set.

        The product resolves credentials from the boto3 default chain, so a
        credential set is switched by replacing that chain's only remaining
        source and recreating the default session the product client is built
        from. The observer is re-attached to each new session.
        """
        os.environ["AWS_ACCESS_KEY_ID"] = access_key_id
        os.environ["AWS_SECRET_ACCESS_KEY"] = secret_access_key
        boto3.setup_default_session()
        self.observer.attach(boto3.DEFAULT_SESSION)
        config = self.objects.object_store_config_from_mapping(product_config_mapping(self.port, bucket))
        if config.bucket != bucket or config.prefix != PREFIX:
            raise SmokeError("configuration: the product did not accept the fixture mapping")
        return self.objects.KnowledgeObjectStore(config)

    def maintenance(self, bucket: str, access_key_id: str, secret_access_key: str):
        """Build the real ``KnowledgeObjectMaintenance`` for one credential set."""
        os.environ["AWS_ACCESS_KEY_ID"] = access_key_id
        os.environ["AWS_SECRET_ACCESS_KEY"] = secret_access_key
        boto3.setup_default_session()
        self.observer.attach(boto3.DEFAULT_SESSION)
        config = self.objects.object_store_config_from_mapping(product_config_mapping(self.port, bucket))
        return self.objects.KnowledgeObjectMaintenance(config)

    def now(self):
        """Naive UTC, the one timestamp convention the product inventory uses."""
        return datetime.now(UTC).replace(tzinfo=None)

    def digest(self, data: bytes) -> str:
        """The content address of ``data``, so a phase module needs no hashing of its own."""
        return _digest(data)

    async def expect_state(self, label: str, call: Callable[[], object], expected) -> None:
        """Assert one product call fails with exactly one product error type."""
        await _expect_state(label, call, self.objects, expected)

    def workspace(self, raw: str):
        return self.knowledge.WorkspaceId.parse(raw)

    def reference(self, bucket: str, key: str, content_sha256: str):
        return self.knowledge.SourceObjectRef(
            bucket=bucket, key=key, content_sha256=content_sha256
        )

    def key(self, workspace: object, content_sha256: str) -> str:
        return self.objects.workspace_object_key(PREFIX, workspace, content_sha256)

    def assert_wire(
        self,
        label: str,
        bucket: str,
        expected: tuple[str, ...],
        *,
        allowed: frozenset[str] = ALLOWED_OPERATIONS,
        list_prefix: str = "",
    ) -> None:
        """Assert the operations, addressing style, headers and list scope of one phase."""
        operations, attempts = self.observer.take()
        # Checked before the exact sequence so a stray operation names itself instead
        # of being reported as a sequence mismatch.
        forbidden = set(operations) - allowed
        if forbidden:
            raise SmokeError(f"{label}: the boundary issued {sorted(forbidden)[0]}")
        if operations != expected:
            raise SmokeError(f"{label}: wire operations were {'+'.join(operations) or 'none'}")
        if len(attempts) != len(operations):
            raise SmokeError(
                f"{label}: {len(attempts)} HTTP attempts for {len(operations)} calls"
            )
        for operation, attempt in zip(operations, attempts, strict=True):
            if attempt.host != self.endpoint_host:
                raise SmokeError(f"{label}: a request did not go to the configured endpoint")
            if not attempt.is_signed:
                raise SmokeError(f"{label}: a request was not signed")
            if not attempt.is_path_style_for(bucket):
                raise SmokeError(f"{label}: a request did not use path-style addressing")
            if operation == "ListObjectsV2" and attempt.list_prefix != list_prefix:
                # A listing without exactly the Workspace prefix would be a bucket-wide read.
                raise SmokeError(f"{label}: a listing was not bounded to the Workspace prefix")
            if operation != "PutObject":
                continue
            if "x-amz-checksum-sha256" not in attempt.header_names:
                raise SmokeError(f"{label}: a write carried no SHA-256 checksum header")
            if attempt.if_none_match != "*":
                raise SmokeError(f"{label}: a write carried no If-None-Match precondition")
        if not expected:
            report_pass(f"{label}: no request reached the wire")
            return
        shape = "+".join(expected)
        # Only what this phase actually asserted: a read-only phase carries no
        # write, so it must not claim a checksum or a precondition was checked.
        checked = "path-style, signed"
        if "PutObject" in expected:
            checked = f"{checked}, checksum and precondition"
        if "ListObjectsV2" in expected:
            checked = f"{checked}, Workspace prefix"
        report_pass(f"{label}: {shape}, {checked}")


async def _expect_state(label: str, call: Callable[[], object], objects, expected) -> None:
    """Assert that a product call fails with exactly one product error type."""
    try:
        await call()
    except objects.KnowledgeObjectError as error:
        if type(error) is not expected:
            raise SmokeError(
                f"{label}: expected {expected.state.value}, got state={error.state.value}"
            ) from None
        report_pass(f"{label}: {error.state.value}")
        return
    raise SmokeError(f"{label}: the call unexpectedly succeeded")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def _immutable_write(context: SmokeContext) -> None:
    """Checksum plus conditional create, the duplicate path, and a verified read."""
    objects = context.objects
    store = context.store(BUCKET, CLIENT_IDENTITY, context.secrets[CLIENT_IDENTITY])
    workspace_1 = context.workspace(WORKSPACE_1)
    workspace_2 = context.workspace(WORKSPACE_2)
    expected_key = context.key(workspace_1, _digest(STORED))

    first = await store.put_if_absent(workspace_1, STORED)
    if not first.created or first.ref.key != expected_key or first.byte_size != len(STORED):
        raise SmokeError("write: the first store did not report a fresh content-addressed object")
    if first.ref.bucket != BUCKET or not first.ref.key.startswith(f"{PREFIX}/knowledge/"):
        raise SmokeError("write: the object was not placed under the configured prefix")
    report_pass("write: checksum plus conditional create stored a new object (created=True)")

    repeat = await store.put_if_absent(workspace_1, STORED)
    if repeat.created or repeat.ref != first.ref:
        raise SmokeError("write: the duplicate write was not recognised as already present")
    report_pass("write: the same content address again answered created=False (412 precondition)")

    if await store.get_verified(workspace_1, first.ref) != STORED:
        raise SmokeError("read: the verified read returned different bytes")
    report_pass("read: the verified read returned exactly the stored bytes")

    partitioned = await store.put_if_absent(workspace_2, STORED)
    if not partitioned.created or partitioned.ref.key == first.ref.key:
        raise SmokeError("isolation: the same bytes did not get a second Workspace partition")
    report_pass("isolation: identical bytes in a second Workspace are a second object")
    context.assert_wire(
        "wire (write path)", BUCKET, ("PutObject", "PutObject", "GetObject", "PutObject")
    )

    await _expect_state(
        "isolation: another Workspace reading this object",
        lambda: store.get_verified(workspace_2, first.ref),
        objects,
        objects.KnowledgeObjectNotFoundError,
    )
    out_of_bucket = context.reference(UNRELATED_BUCKET, first.ref.key, first.ref.content_sha256)
    await _expect_state(
        "isolation: a reference to another bucket",
        lambda: store.get_verified(workspace_1, out_of_bucket),
        objects,
        objects.KnowledgeObjectNotFoundError,
    )
    context.assert_wire("wire (isolation refusals)", BUCKET, ())


async def _absent_and_corrupt(context: SmokeContext) -> None:
    """Absent object, a planted digest mismatch, and an absent bucket."""
    objects = context.objects
    store = context.store(BUCKET, CLIENT_IDENTITY, context.secrets[CLIENT_IDENTITY])
    workspace_1 = context.workspace(WORKSPACE_1)

    unstored_digest = _digest(UNSTORED)
    absent = context.reference(BUCKET, context.key(workspace_1, unstored_digest), unstored_digest)
    await _expect_state(
        "absent object",
        lambda: store.get_verified(workspace_1, absent),
        objects,
        objects.KnowledgeObjectNotFoundError,
    )

    # Server capability, not a product call: the boundary depends on the server
    # validating the digest it is addressed by, and the product cannot produce a
    # mismatch itself. The fixture identity and its own session are used, so this
    # write never appears in the product wire record.
    rejected_with = await asyncio.to_thread(
        context.admin.checksum_rejection_code,
        BUCKET,
        context.key(context.workspace(WORKSPACE_2), _digest(PLANTED)),
        PLANTED,
        base64.b64encode(bytes.fromhex(_digest(STORED))).decode("ascii"),
    )
    if not rejected_with:
        raise SmokeError("server capability: a write with a wrong SHA-256 checksum was accepted")
    report_pass(f"server capability: a wrong SHA-256 checksum is refused ({rejected_with})")

    addressed_digest = _digest(ADDRESSED)
    corrupt_key = context.key(workspace_1, addressed_digest)
    await asyncio.to_thread(context.admin.plant_object, BUCKET, corrupt_key, PLANTED)
    corrupt = context.reference(BUCKET, corrupt_key, addressed_digest)
    await _expect_state(
        "stored bytes that disagree with their content address",
        lambda: store.get_verified(workspace_1, corrupt),
        objects,
        objects.KnowledgeObjectIntegrityError,
    )
    context.assert_wire("wire (absent and corrupt reads)", BUCKET, ("GetObject", "GetObject"))

    absent_store = context.store(ABSENT_BUCKET, CLIENT_IDENTITY, context.secrets[CLIENT_IDENTITY])
    await _expect_state(
        "absent bucket on write",
        lambda: absent_store.put_if_absent(workspace_1, UNSTORED),
        objects,
        objects.KnowledgeObjectNotConfiguredError,
    )
    in_absent = context.reference(
        ABSENT_BUCKET, context.key(workspace_1, unstored_digest), unstored_digest
    )
    await _expect_state(
        "absent bucket on read",
        lambda: absent_store.get_verified(workspace_1, in_absent),
        objects,
        objects.KnowledgeObjectNotConfiguredError,
    )
    context.assert_wire("wire (absent bucket)", ABSENT_BUCKET, ("PutObject", "GetObject"))


async def _authorization(context: SmokeContext) -> None:
    """A refused grant, a wrong secret and an unknown access key."""
    objects = context.objects
    workspace_1 = context.workspace(WORKSPACE_1)
    stored_digest = _digest(STORED)
    reference = context.reference(BUCKET, context.key(workspace_1, stored_digest), stored_digest)
    cases = (
        ("no grant on this bucket", DENIED_IDENTITY, context.secrets[DENIED_IDENTITY]),
        ("a wrong secret key", CLIENT_IDENTITY, "0" * 48),
        ("an unknown access key", "octryx-local-smoke-unknown-client", context.secrets[CLIENT_IDENTITY]),
    )
    for label, access_key_id, secret_key in cases:
        store = context.store(BUCKET, access_key_id, secret_key)
        await _expect_state(
            f"authorization ({label}): writing",
            lambda store=store: store.put_if_absent(workspace_1, UNSTORED),
            objects,
            objects.KnowledgeObjectUnauthorizedError,
        )
        await _expect_state(
            f"authorization ({label}): reading",
            lambda store=store: store.get_verified(workspace_1, reference),
            objects,
            objects.KnowledgeObjectUnauthorizedError,
        )
        context.assert_wire(f"wire ({label})", BUCKET, ("PutObject", "GetObject"))


async def _run(knowledge, objects, secrets: Mapping[str, str], port: int) -> None:
    context = SmokeContext(
        knowledge=knowledge,
        objects=objects,
        observer=WireObserver(),
        admin=FixtureAdmin(
            endpoint_url=f"http://{HOST}:{port}",
            region=REGION,
            access_key_id=ADMIN_IDENTITY,
            secret_access_key=secrets[ADMIN_IDENTITY],
        ),
        secrets=secrets,
        port=port,
    )
    attempts = await asyncio.to_thread(context.admin.wait_until_bucket_exists, BUCKET)
    report_pass(f"readiness: the runtime accepted the fixture bucket after {attempts} attempt(s)")

    await _immutable_write(context)
    await _absent_and_corrupt(context)
    await _authorization(context)
    await run_reconciliation(context)


def main() -> int:
    # Only the fixed PASS/FAIL lines below are emitted; library logging stays silent.
    logging.disable(logging.CRITICAL)
    try:
        knowledge, objects = _load_product()
        port = port_from_environment()
        secrets = read_identities(_CHECKOUT)
        neutralize_ambient_aws()
        asyncio.run(_run(knowledge, objects, secrets, port))
    except (SmokeError, FixtureError) as failure:
        print(f"FAIL {failure}", file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print("FAIL interrupted", file=sys.stderr, flush=True)
        return 130
    except Exception as error:  # process boundary: never print messages or tracebacks
        objects = sys.modules.get("app.services.knowledge.objects")
        if objects is not None and isinstance(error, objects.KnowledgeObjectError):
            operation = error.operation.value if error.operation else "none"
            line = f"state={error.state.value} operation={operation}"
        else:
            line = f"unexpected {type(error).__name__}"
        print(f"FAIL product boundary: {line}", file=sys.stderr, flush=True)
        return 1
    report_pass("product smoke: the real KnowledgeObjectStore passed every protocol check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
