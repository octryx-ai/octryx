"""Ship the generic phased workflows: created once, updated only while nobody changed them.

A missing seeded workflow is created and its version published. An existing one is updated by a changed seed
only while its published version still is the seed this code wrote (its definition's digest is the version's
``runtime_settings.seed_digest``) and no draft is pending: the new seed becomes a new published version. An admin's
version is never overwritten: the changed seed waits next to it as one draft version for review,
and an archived workflow stays archived. The definitions are generic — no customer
values; a Workspace binds them through its own Jira, repository and CI connections.
"""

from __future__ import annotations

import json
import logging
from hashlib import sha256
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import FlowDefinition, User

logger = logging.getLogger(__name__)
SEEDS_PATH = Path(__file__).resolve().parent / "seeds" / "phased_workflows.json"
SEED_MARKER = "phased_workflows"
# The shipped fragments (``sf-publish-prove``), seeded before the workflows whose source pins them.
FRAGMENT_SEEDS_PATH = Path(__file__).resolve().parent / "seeds" / "phased_fragments.json"
FRAGMENT_SEED_MARKER = "phased_fragments"

# Which shipped workflows a fresh installation has active: ``availability`` per seed, "default"
# (active) or "optional" (shipped inactive; an admin switches it on). An existing flow keeps its own switch.
AVAILABILITY_OPTIONAL = "optional"


def definition_digest(definition: Any) -> str:
    return "sha256:" + sha256(json.dumps(definition, sort_keys=True).encode("utf-8")).hexdigest()


def phased_fragment_seeds() -> list[dict[str, Any]]:
    return json.loads(FRAGMENT_SEEDS_PATH.read_text(encoding="utf-8"))


def _seed_composition(seed: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """A ``definition_source`` seed compiled with the fragment seed file (pure, pinned by checksum)."""
    from .fragments.compiler import compile_composite, composition_settings
    from .fragments.format import FragmentError, ResolvedFragment, fragment_refs, parse_fragment
    from .handoff.contract import canonical_hash

    source = seed["definition_source"]
    shipped = {(item["key"], canonical_hash(item["definition"])): item for item in phased_fragment_seeds()}
    resolved = {}
    for ref in fragment_refs(source):
        fragment = shipped.get((ref.fragment_key, ref.checksum))
        if fragment is None:
            raise FragmentError([{"code": "fragment_pin_unresolved", "message": (
                f"Seed {seed['key']}: no shipped fragment {ref.fragment_key} with checksum {ref.checksum}.")}])
        resolved[ref.node_id] = ResolvedFragment(
            key=ref.fragment_key, version_id="", version=1, checksum=ref.checksum,
            definition=parse_fragment(fragment["definition"]))
    composition = compile_composite(source, resolved)
    return composition.definition, composition_settings(composition, source)


def phased_seeds() -> list[dict[str, Any]]:
    """The shipped workflows; a ``definition_source`` seed (B) also gets its compiled ``definition``."""
    return [compiled_seed(seed) for seed in json.loads(SEEDS_PATH.read_text(encoding="utf-8"))]


def compiled_seed(seed: dict[str, Any]) -> dict[str, Any]:
    """A seed with its ``definition``: a ``definition_source`` seed is compiled with the shipped fragments."""
    return {**seed, "definition": _seed_composition(seed)[0]} if "definition_source" in seed else seed


async def _pinned_composition(db: AsyncSession, seed: dict[str, Any]) -> dict[str, Any] | None:
    """The composition block of a NEW version of a ``definition_source`` seed, with the seeded fragment versions'
    ids and numbers (resolved by key + checksum). Never written onto an existing version."""
    if "definition_source" not in seed:
        return None
    from ...models.runtime.flow_definition import FlowDefinitionVersion
    from .handoff.contract import canonical_hash

    _definition, composition = _seed_composition(seed)
    pins: dict[tuple[str, str], tuple[str, int]] = {}
    for item in composition.get("fragments") or []:
        rows = (await db.execute(select(FlowDefinitionVersion).join(
            FlowDefinition, FlowDefinition.id == FlowDefinitionVersion.flow_id).where(
            FlowDefinition.key == item["key"], FlowDefinition.project_id.is_(None),
            FlowDefinitionVersion.status == "published"))).scalars().all()
        match = next((row for row in rows if canonical_hash(row.definition_json or {}) == item["checksum"]), None)
        if match is not None:
            pins[(item["key"], item["checksum"])] = (match.id, match.version)
    for entry in [*(composition.get("fragments") or []), *dict(composition.get("provenance") or {}).values()]:
        pin = pins.get((entry.get("key"), entry.get("checksum")))
        if pin is not None:
            entry["version_id"], entry["version"] = pin
    return composition


def _fragment_keys(node: Any) -> set[str]:
    """The ``fragment_key`` every fragment box of a definition (or its source) names."""
    if isinstance(node, dict):
        own = {str(node["fragment_key"])} if node.get("fragment_key") else set()
        return own.union(*(_fragment_keys(value) for value in node.values()))
    if isinstance(node, list):
        return set().union(*(_fragment_keys(value) for value in node))
    return set()


def _used_fragments() -> set[str]:
    """The fragments a shipped workflow uses: a fresh installation is not shown a part no workflow of it runs."""
    return _fragment_keys(json.loads(SEEDS_PATH.read_text(encoding="utf-8")))


async def seed_phased_fragments(db: AsyncSession, *, admin_user: User) -> dict[str, int]:
    """Create and publish the shipped fragments once (seeds are exempt from fragment four-eyes); a changed
    fragment seed follows the same admin-overwrite rules as a workflow seed (:func:`_update_seed`)."""
    from ..flow_definitions import create_flow_definition, publish_flow_definition_version

    counts = {"created": 0, "updated": 0, "unchanged": 0}
    hidden = {"capability_enabled": False, "llm_visible": False}
    used = _used_fragments()
    for seed in phased_fragment_seeds():
        digest = definition_digest(seed["definition"])
        existing = (await db.execute(select(FlowDefinition).where(
            FlowDefinition.key == seed["key"], FlowDefinition.project_id.is_(None)))).scalars().first()
        if existing is None and seed["key"] not in used:
            continue  # no workflow of this installation uses it: a fresh one is not shown a part nobody runs
        if existing is not None:
            updated = await _update_seed(db, existing, seed, digest, admin_user, marker=FRAGMENT_SEED_MARKER,
                                         publish_metadata=hidden)
            counts["updated" if updated else "unchanged"] += 1
            continue
        created = await create_flow_definition(db, current_user=admin_user, payload={
            "key": seed["key"], "name": seed["name"], "description": seed["description"],
            "definition": seed["definition"],
            "runtime_settings": {"seed": FRAGMENT_SEED_MARKER, "seed_digest": digest},
        })
        await publish_flow_definition_version(db, version_id=created["versions"][0]["id"], current_user=admin_user,
                                              publish_metadata=hidden, shipped=True)
        counts["created"] += 1
        logger.info("Seeded phased fragment: key=%s", seed["key"])
    await db.flush()
    return counts


async def seed_phased_workflows(db: AsyncSession, *, admin_user: User) -> dict[str, int]:
    from ..flow_definitions import create_flow_definition, publish_flow_definition_version

    fragments = await seed_phased_fragments(db, admin_user=admin_user)
    counts: dict[str, Any] = {"created": 0, "updated": 0, "unchanged": 0}
    for seed in phased_seeds():
        digest = definition_digest(seed["definition"])
        existing = (await db.execute(select(FlowDefinition).where(
            FlowDefinition.key == seed["key"], FlowDefinition.project_id.is_(None)))).scalars().first()
        if existing is not None:
            # A switched-off optional workflow still gets the shipped content (publishing needs it on for a moment).
            off = not existing.is_active and seed.get("availability") == AVAILABILITY_OPTIONAL \
                and existing.status != "archived"
            existing.is_active = existing.is_active or off
            try:
                updated = await _update_seed(db, existing, seed, digest, admin_user)
            finally:
                if off:
                    existing.is_active = False
            counts["updated" if updated else "unchanged"] += 1
            continue
        created = await create_flow_definition(db, current_user=admin_user, payload={
            "key": seed["key"], "name": seed["name"], "description": seed["description"],
            "definition": seed["definition"], "runtime_settings": {
                "seed": SEED_MARKER, "seed_digest": digest,
                **({"composition": composition} if (composition := await _pinned_composition(db, seed)) else {})},
        })
        await publish_flow_definition_version(db, version_id=created["versions"][0]["id"], current_user=admin_user,
                                              shipped=True)  # shipped content: exempt from four-eyes
        if seed.get("availability") == AVAILABILITY_OPTIONAL:  # shipped, published, and off until an admin wants it
            flow = await db.get(FlowDefinition, created["id"])
            if flow is not None:
                flow.is_active = False
        counts["created"] += 1
        logger.info("Seeded phased workflow: key=%s", seed["key"])
    await db.flush()
    counts["fragments"] = fragments
    return counts


async def _update_seed(db: AsyncSession, flow: FlowDefinition, seed: dict[str, Any], digest: str,
                       admin_user: User, *, marker: str = SEED_MARKER,
                       publish_metadata: dict[str, Any] | None = None) -> bool:
    """A changed seed becomes a new published version while the current one is still a shipped seed."""
    from ...models.runtime.flow_definition import FlowDefinitionVersion
    from ..flow_definitions import next_flow_version_number, publish_flow_definition_version, validate_flow_definition

    if flow.status == "archived" or (not flow.is_active and seed.get("availability") != AVAILABILITY_OPTIONAL):
        # An admin archived it: never revived, and never a publish that would refuse and abort the bootstrap.
        logger.info("Changed phased seed not applied: the workflow is archived (key=%s)", seed["key"])
        return False
    current = await db.get(FlowDefinitionVersion, flow.current_version_id or "")
    if current is None or current.status != "published":
        return False
    from .canvas_layout import LAYOUT_KEY, layout_positions, with_layout

    # Where the designer draws the boxes is not ownership: a moved box keeps the shipped seed updatable.
    current_definition = dict(current.definition_json or {})
    current_digest = definition_digest({k: v for k, v in current_definition.items() if k != LAYOUT_KEY})
    # A seed that ships its own ``layout`` (team-delivery: direction "tb") is digested WITH it; the stored definition's
    # digest is compared both ways, or such a seeded version would count as admin-owned.
    full_digest = definition_digest(current_definition)
    if digest in (current_digest, full_digest):
        return False
    seeded = str(dict(current.runtime_settings or {}).get("seed_digest") or "")
    admin_owned = seeded not in (current_digest, full_digest)
    drafts = (await db.execute(select(FlowDefinitionVersion).where(
        FlowDefinitionVersion.flow_id == flow.id, FlowDefinitionVersion.status == "draft"))).scalars().all()
    seed_drafts = [item for item in drafts if dict(item.runtime_settings or {}).get("seed")]
    if drafts and not admin_owned and len(seed_drafts) == len(drafts):
        # Only seed drafts are pending on a shipped workflow: the newest seed replaces the oldest of them and is
        # published (nothing is deleted; an admin's own draft still blocks, below).
        version = seed_drafts[0]
        from .graph import parse_phased_definition

        version.definition_json = seed["definition"] if "definition_source" in seed else with_layout_of(
            seed["definition"], current_definition, parse_phased_definition)
        version.validation_report = validate_flow_definition(version.definition_json)
        version.runtime_settings = {**dict(version.runtime_settings or {}), "seed": marker, "seed_digest": digest}
        await db.flush()
        await publish_flow_definition_version(db, version_id=version.id, current_user=admin_user,
                                              publish_metadata=publish_metadata, shipped=True)
        logger.info("Phased seed published from its pending seed draft: key=%s", seed["key"])
        return True
    if drafts:
        logger.info("Changed phased seed not applied: a draft is pending (key=%s)", seed["key"])
        return False
    if admin_owned and await _seed_version_exists(db, flow, digest):
        return False
    # The new seed version keeps the boxes the admin placed for the nodes it still has. Not for a composite: its
    # stored graph must stay exactly the compiled composition (``fragments.store`` checks the digest).
    from .graph import parse_phased_definition

    definition = seed["definition"] if "definition_source" in seed else with_layout(seed["definition"], (
        layout_positions(current_definition, frozenset(parse_phased_definition(seed["definition"]).nodes))))
    version = FlowDefinitionVersion(
        flow_id=flow.id, version=await next_flow_version_number(db, flow_id=flow.id), status="draft",
        definition_json=definition, validation_report=validate_flow_definition(definition),
        publish_metadata={}, runtime_settings={
            "seed": marker, "seed_digest": digest,
            **({"composition": composition} if (composition := await _pinned_composition(db, seed)) else {})},
        policy_bindings={}, created_by=admin_user.id)
    db.add(version)
    await db.flush()
    if admin_owned:
        logger.info("Changed phased seed waits as a draft: an admin owns the workflow (key=%s)", seed["key"])
        return False
    await publish_flow_definition_version(db, version_id=version.id, current_user=admin_user,
                                          publish_metadata=publish_metadata, shipped=True)
    logger.info("Phased seed published as a new version: key=%s", seed["key"])
    return True


def with_layout_of(definition: dict[str, Any], current: dict[str, Any], parse: Any) -> dict[str, Any]:
    from .canvas_layout import layout_positions, with_layout

    return with_layout(definition, layout_positions(current, frozenset(parse(definition).nodes)))


async def _seed_version_exists(db: AsyncSession, flow: FlowDefinition, digest: str) -> bool:
    """This seed was already offered (as a draft an admin since published, discarded or kept): never again."""
    from ...models.runtime.flow_definition import FlowDefinitionVersion

    versions = (await db.execute(select(FlowDefinitionVersion.runtime_settings).where(
        FlowDefinitionVersion.flow_id == flow.id))).scalars().all()
    return any(str(dict(item or {}).get("seed_digest") or "") == digest for item in versions)


__all__ = ["compiled_seed", "definition_digest", "phased_fragment_seeds",
           "phased_seeds", "seed_phased_fragments", "seed_phased_workflows", "AVAILABILITY_OPTIONAL"]
