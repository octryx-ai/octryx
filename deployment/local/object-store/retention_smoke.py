"""Live acceptance of the operator-owned reconciliation capability.

One phase of ``product_smoke.py``, in its own module because it drives a different product
class with a different identity and a different privilege set: the immutable store is
``PutObject``/``GetObject`` with the Knowledge client identity, while
``KnowledgeObjectMaintenance`` is ``ListObjectsV2``/``DeleteObject`` with the reconciliation
identity, which holds no ``Read`` grant at all.

What it proves against the pinned real server rather than a double:

- a listing is always bounded to one Workspace's derived key prefix — the ``prefix``
  parameter is read back off the wire, so a bucket-wide list would fail here;
- every entry carries the content address, the byte size and the write time the object
  really has, normalised to naive UTC;
- a key under the Workspace prefix that the product never derives is counted and is not
  deletable — including the narrow case that containment alone accepts, a well-shaped key
  whose fan-out segments do not belong to the digest behind them;
- bounded pages continue deterministically after the last key, with no server cursor;
- another Workspace's object never appears in a listing, and deleting it — or any
  non-derived key — is refused *without a request reaching the wire*;
- one approved deletion removes exactly one object and leaves the rest untouched;
- the reconciliation identity cannot read an object's bytes.

No credential, object body or server error body is printed; output is fixed text plus
product state names.
"""

from __future__ import annotations

import asyncio

from fixture_client import FixtureAdmin
from fixture_contract import (
    ADDRESSED,
    BUCKET,
    HOST,
    REGION,
    RETENTION_IDENTITY,
    STORED,
    WORKSPACE_1,
    WORKSPACE_2,
    SmokeError,
    report_pass,
)
from wire_observer import MAINTENANCE_OPERATIONS


async def run_reconciliation(context) -> None:
    """The operator-owned inventory and single-object deletion.

    Runs last on purpose: it reconciles the objects the phases above really wrote.
    """
    objects = context.objects
    maintain = context.maintenance(BUCKET, RETENTION_IDENTITY, context.secrets[RETENTION_IDENTITY])
    workspace_1 = context.workspace(WORKSPACE_1)
    workspace_2 = context.workspace(WORKSPACE_2)
    prefix_1 = maintain.workspace_key_prefix(workspace_1)
    prefix_2 = maintain.workspace_key_prefix(workspace_2)
    stored_key = context.key(workspace_1, context.digest(STORED))
    corrupt_key = context.key(workspace_1, context.digest(ADDRESSED))

    # Two keys under the Workspace prefix that the product never derives: both must be
    # counted and neither may ever become a deletion candidate. The second one is the narrow
    # case containment alone accepts — a well-shaped key whose fan-out segments do not belong
    # to the digest behind them, which only the content-address predicate rejects.
    stray_key = f"{prefix_1}sha256/aa/bb/not-a-content-address"
    mismatched_key = f"{prefix_1}sha256/ff/ff/{context.digest(STORED)}"
    for planted in (stray_key, mismatched_key):
        await asyncio.to_thread(context.admin.plant_object, BUCKET, planted, b"stray\n")

    page = await maintain.list_workspace(workspace_1)
    listed = {item.key: item for item in page.objects}
    if set(listed) != {stored_key, corrupt_key}:
        raise SmokeError("inventory: the listing did not return exactly this Workspace's objects")
    if page.unrecognized_count != 2 or page.truncated or page.next_after_key is not None:
        raise SmokeError("inventory: an undirected key was not counted as unrecognized")
    if listed[stored_key].byte_size != len(STORED) or listed[stored_key].content_sha256 != context.digest(STORED):
        raise SmokeError("inventory: an entry did not carry the content address and size it stores")
    if listed[stored_key].last_modified.tzinfo is not None:
        raise SmokeError("inventory: a write time was not normalised to naive UTC")
    if listed[stored_key].age_hours(context.now()) < 0:
        raise SmokeError("inventory: an object age was negative")
    report_pass("inventory: exactly this Workspace's objects, with address, size and write time")
    context.assert_wire(
        "wire (inventory)", BUCKET, ("ListObjectsV2",), allowed=MAINTENANCE_OPERATIONS, list_prefix=prefix_1
    )

    bounded = await maintain.list_workspace(workspace_1, limit=1)
    if len(bounded.objects) != 1 or not bounded.truncated or bounded.next_after_key is None:
        raise SmokeError("inventory: a bounded page did not report that more results exist")
    rest = await maintain.list_workspace(workspace_1, after_key=bounded.next_after_key)
    if {item.key for item in bounded.objects} | {item.key for item in rest.objects} != set(listed):
        raise SmokeError("inventory: paging did not return every object exactly once")
    report_pass("inventory: bounded pages continue deterministically after the last key")
    context.assert_wire(
        "wire (inventory paging)",
        BUCKET,
        ("ListObjectsV2", "ListObjectsV2"),
        allowed=MAINTENANCE_OPERATIONS,
        list_prefix=prefix_1,
    )

    other = await maintain.list_workspace(workspace_2)
    if not other.objects or {item.key for item in other.objects} & set(listed):
        raise SmokeError("isolation: a Workspace listing returned another Workspace's object")
    report_pass("isolation: a Workspace listing never returns another Workspace's object")
    context.assert_wire(
        "wire (isolation inventory)",
        BUCKET,
        ("ListObjectsV2",),
        allowed=MAINTENANCE_OPERATIONS,
        list_prefix=prefix_2,
    )

    foreign_key = next(iter({item.key for item in other.objects}))
    await context.expect_state(
        "isolation: deleting an object of another Workspace",
        lambda: maintain.delete_one(workspace_1, foreign_key),
        objects.KnowledgeObjectNotFoundError,
    )
    await context.expect_state(
        "isolation: deleting a key the product never derives",
        lambda: maintain.delete_one(workspace_1, stray_key),
        objects.KnowledgeObjectNotFoundError,
    )
    await context.expect_state(
        "isolation: deleting a contained key that is not content-addressed",
        lambda: maintain.delete_one(workspace_1, mismatched_key),
        objects.KnowledgeObjectNotFoundError,
    )
    context.assert_wire(
        "wire (deletion refusals)", BUCKET, (), allowed=MAINTENANCE_OPERATIONS
    )

    await maintain.delete_one(workspace_1, corrupt_key)
    remaining = await maintain.list_workspace(workspace_1)
    if {item.key for item in remaining.objects} != {stored_key}:
        raise SmokeError("deletion: the listing after the delete is not the expected remainder")
    report_pass("deletion: exactly one addressed object was removed, the other is untouched")
    context.assert_wire(
        "wire (deletion)",
        BUCKET,
        ("DeleteObject", "ListObjectsV2"),
        allowed=MAINTENANCE_OPERATIONS,
        list_prefix=prefix_1,
    )

    # The reconciliation identity holds List and Write on the bucket and no Read grant, so
    # it cannot read Workspace bytes. The product capability has no read operation at all,
    # which is why this is measured from outside product code.
    reader = FixtureAdmin(
        endpoint_url=f"http://{HOST}:{context.port}",
        region=REGION,
        access_key_id=RETENTION_IDENTITY,
        secret_access_key=context.secrets[RETENTION_IDENTITY],
    )
    refused_with = await asyncio.to_thread(reader.get_rejection_code, BUCKET, stored_key)
    if refused_with not in ("AccessDenied", "403"):
        raise SmokeError(
            f"least privilege: the reconciliation identity could read an object ({refused_with or 'accepted'})"
        )
    report_pass(f"least privilege: the reconciliation identity cannot read an object ({refused_with})")
