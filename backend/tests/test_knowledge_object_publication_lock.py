"""The publication boundary of a Workspace Knowledge object.

The ingestion boundary writes the immutable object before it commits the revision that
references it. The guarantee that nothing interleaves there is PostgreSQL's transaction-scoped
advisory lock (``app/services/knowledge/objects/publication_lock.py``). This module pins the key
derivation and the explicit "not held on this engine" answer; the two-connection proof lives in
``test_knowledge_object_publication_lock_postgres``.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.knowledge.ledger.advisory_locks import advisory_lock_key
from app.services.knowledge.objects.publication_lock import (
    LOCK_NAMESPACE,
    ObjectPublicationLockError,
    lock_object_publication,
    publication_lock_key,
    serializes_object_publication,
)
from app.services.knowledge.retention.governance_lock import GOVERNANCE_LOCK_NAMESPACE, governance_lock_key

# --- the derivation ---------------------------------------------------------


def test_the_lock_key_is_deterministic_per_workspace_and_object():
    """The one property the boundary needs, stated exactly.

    A lock key is only ever used to *acquire* mutual exclusion, so correctness needs equal
    inputs to derive the equal key — nothing more. Distinctness is *not* claimed: 64 bits
    truncated from a SHA-256 can collide, and a collision would make two unrelated objects
    serialize against each other, which is extra waiting rather than a boundary that fails to
    hold. So this asserts determinism, the signed 64-bit range, and that these specific
    neighbouring inputs really do separate — never that no pair anywhere can share a key.
    """
    workspace = str(uuid.uuid4())
    other = str(uuid.uuid4())
    key = "octryx/test/knowledge/octryx_ws_" + "0" * 32 + "/sha256/aa/bb/" + "aabb" + "c" * 60

    # Deterministic: the ingestion and the deletion pass compute the same key, in any process.
    assert publication_lock_key(workspace, key) == publication_lock_key(workspace, key)
    # These inputs separate. The NUL separator is why no pair can be re-cut into another pair's
    # digest input, which is the only "collision" this derivation actually rules out.
    assert publication_lock_key(workspace, key) != publication_lock_key(other, key)
    assert publication_lock_key(workspace, key) != publication_lock_key(workspace, key + "0")
    assert publication_lock_key("ab", "c") != publication_lock_key("a", "bc")
    # The namespace is part of the digest and versioned, so an unrelated future advisory-lock
    # user of this database is separated by construction rather than by luck.
    assert LOCK_NAMESPACE.endswith(".v1")
    assert publication_lock_key(workspace, key) != advisory_lock_key(
        "octryx.something.else.v1", workspace, key
    )
    # In range for the one ``bigint`` argument ``pg_advisory_xact_lock`` takes.
    assert -(2**63) <= publication_lock_key(workspace, key) < 2**63


def test_the_governance_key_is_a_separate_namespace_from_the_publication_key():
    """Two boundaries, one advisory-lock space: the namespaces are what keeps them apart."""
    workspace = str(uuid.uuid4())
    assert GOVERNANCE_LOCK_NAMESPACE != LOCK_NAMESPACE
    assert governance_lock_key(workspace) == governance_lock_key(workspace)
    assert governance_lock_key(workspace) != publication_lock_key(workspace, workspace)
    assert -(2**63) <= governance_lock_key(workspace) < 2**63


def test_an_unusable_workspace_or_key_is_a_defect_and_carries_no_value():
    """A fixed message per class, so no caller can place a key into a raised error."""
    messages = set()
    for project_id, object_key in (("", "k"), ("ws", ""), (None, "k"), ("ws", 7), ("ws", b"k")):
        with pytest.raises(ObjectPublicationLockError) as raised:
            publication_lock_key(project_id, object_key)
        messages.add(str(raised.value))
    assert messages == {"object publication lock requires a workspace id and an object key"}


# --- the explicit answer on an engine without advisory locks -----------------


async def test_the_boundary_reports_that_it_is_not_held_instead_of_pretending(db):
    """The SQLite harness cannot hold it, and says so rather than answering success."""
    assert serializes_object_publication(db) is False
    lock = await lock_object_publication(db, project_id="ws", object_key="key")
    assert lock.serialized is False
    assert lock.lock_key == publication_lock_key("ws", "key")
