"""Fragment storage, pins and the publish rules."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import FlowDefinition, FlowDefinitionVersion

if TYPE_CHECKING:
    from .format import ResolvedFragment

COMPOSITION_KEY = "composition"
# The marker the platform's fragment seeder writes; only such a version is exempt from four-eyes.
FRAGMENT_SEED_MARKER = "phased_fragments"
SEED_KEYS = ("seed", "seed_digest")

PIN_UNRESOLVED = "fragment_pin_unresolved"
PIN_CHANGED = "fragment_pin_changed"
NOT_PUBLISHED = "fragment_not_published"
SCOPE = "fragment_scope"
COMPOSITION_DRIFT = "fragment_composition_drift"
FOUR_EYES_REASON = "fragment_four_eyes"
NODE_READ_ONLY = "fragment_node_read_only"


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def is_fragment(definition: Any) -> bool:
    from .format import is_fragment_definition

    return is_fragment_definition(definition)


def is_composite(definition: Any) -> bool:
    from .format import is_composite_source

    return is_composite_source(definition)


def composition_of(version: FlowDefinitionVersion | None) -> dict[str, Any] | None:
    settings = dict(version.runtime_settings or {}) if version is not None else {}
    block = settings.get(COMPOSITION_KEY)
    return block if isinstance(block, dict) and block else None


def requires_version_id(runtime_settings: Any) -> bool:
    return not (isinstance(runtime_settings, dict) and runtime_settings.get("seed"))


async def _pinned_version(db: AsyncSession, version_id: str, *, lock: bool) -> FlowDefinitionVersion | None:
    stmt = select(FlowDefinitionVersion).where(FlowDefinitionVersion.id == version_id)
    if lock:
        stmt = stmt.with_for_update(read=True).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _version_by_checksum(
    db: AsyncSession, key: str, checksum: str, *, project_id: str | None, lock: bool
) -> FlowDefinitionVersion | None:
    from ..handoff.contract import canonical_hash

    stmt = (
        select(FlowDefinitionVersion)
        .join(FlowDefinition, FlowDefinition.id == FlowDefinitionVersion.flow_id)
        .where(FlowDefinition.key == key, FlowDefinitionVersion.status == "published",
               or_(FlowDefinition.project_id.is_(None), FlowDefinition.project_id == project_id))
        .order_by(FlowDefinitionVersion.version.desc())
    )
    if lock:
        stmt = stmt.with_for_update(read=True).execution_options(populate_existing=True)
    for version in (await db.execute(stmt)).scalars().all():
        if canonical_hash(dict(version.definition_json or {})) == checksum:
            return version
    return None


async def resolve_fragment_pins(
    db: AsyncSession,
    source: dict,
    *,
    project_id: str | None,
    require_version_id: bool = True,
    lock: bool = False,
) -> dict[str, ResolvedFragment]:
    from ..handoff.contract import canonical_hash
    from .format import FragmentError, ResolvedFragment, fragment_refs, is_fragment_definition, parse_fragment

    errors: list[dict[str, str]] = []
    resolved: dict[str, ResolvedFragment] = {}
    for ref in fragment_refs(source):
        label = f"Fragment reference '{ref.node_id}' ({ref.fragment_key})"
        if ref.version_id:
            version = await _pinned_version(db, ref.version_id, lock=lock)
        elif require_version_id:
            errors.append(_error(PIN_UNRESOLVED, f"{label} must pin a fragment version id and its checksum."))
            continue
        else:
            version = await _version_by_checksum(db, ref.fragment_key, ref.checksum, project_id=project_id,
                                                 lock=lock)
        flow = await db.get(FlowDefinition, version.flow_id) if version is not None else None
        definition = dict(version.definition_json or {}) if version is not None else {}
        if version is None or flow is None or flow.key != ref.fragment_key or not is_fragment_definition(definition):
            errors.append(_error(PIN_UNRESOLVED, f"{label} pins no version of that fragment."))
            continue
        if flow.project_id is not None and flow.project_id != project_id:
            errors.append(_error(SCOPE, f"{label} belongs to another Workspace."))
            continue
        if version.status != "published" or flow.status == "archived" or not flow.is_active:
            errors.append(_error(NOT_PUBLISHED, f"{label}: the pinned fragment version is not published."))
            continue
        checksum = canonical_hash(definition)
        if checksum != ref.checksum:
            errors.append(_error(PIN_CHANGED, f"{label}: the pinned checksum is not that version's content; "
                                              "re-pin the fragment explicitly."))
            continue
        try:
            parsed = parse_fragment(definition)
        except FragmentError as error:
            errors.extend(error.errors)
            continue
        resolved[ref.node_id] = ResolvedFragment(key=flow.key, version_id=version.id, version=int(version.version),
                                                 checksum=checksum, definition=parsed)
    if errors:
        raise FragmentError(errors)
    return resolved


def _summary(settings: dict[str, Any]) -> dict[str, Any]:
    return {"fragments": list(settings.get("fragments") or []), "compiled_digest": settings.get("compiled_digest"),
            "source_hash": settings.get("source_hash")}


async def compose_for_save(
    db: AsyncSession,
    definition: dict,
    *,
    project_id: str | None,
    require_version_id: bool = True,
) -> tuple[dict, dict | None]:
    if not is_composite(definition):
        return definition, None
    from .compiler import compile_composite, composition_settings
    from .format import FragmentError
    from .validation import validate_composition

    resolved = await resolve_fragment_pins(db, definition, project_id=project_id,
                                           require_version_id=require_version_id)
    report = validate_composition(definition, resolved)
    if not report.get("valid"):
        raise FragmentError(list(report.get("errors") or []))
    composition = compile_composite(definition, resolved)
    return composition.definition, composition_settings(composition, definition)


async def validate_source(
    db: AsyncSession, definition: dict, *, project_id: str | None
) -> tuple[dict[str, Any], dict | None]:
    from .compiler import compile_composite
    from .format import FragmentError
    from .validation import validate_composition

    try:
        resolved = await resolve_fragment_pins(db, definition, project_id=project_id)
        report = dict(validate_composition(definition, resolved))
        compiled = compile_composite(definition, resolved).definition if report.get("valid") else None
    except FragmentError as error:
        return {"valid": False, "errors": list(error.errors), "warnings": []}, None
    return report, compiled


async def verify_composition_at_publish(
    db: AsyncSession, version: FlowDefinitionVersion, *, project_id: str | None
) -> list[dict]:
    block = composition_of(version)
    if block is None:
        return []
    source = block.get("source")
    if not isinstance(source, dict) or not is_composite(source):
        return [_error(COMPOSITION_DRIFT, "The stored composition has no composite source.")]
    from ..seeding import definition_digest
    from .compiler import compile_composite
    from .format import FragmentError

    try:
        resolved = await resolve_fragment_pins(db, source, project_id=project_id, lock=True,
                                               require_version_id=requires_version_id(version.runtime_settings))
        composition = compile_composite(source, resolved)
    except FragmentError as error:
        return list(error.errors)
    stored = definition_digest(dict(version.definition_json or {}))
    if composition.compiled_digest != stored or definition_digest(composition.definition) != stored:
        return [_error(COMPOSITION_DRIFT, "The stored workflow graph is not the compiled composition of its "
                                          "pinned fragments; save a new draft.")]
    return []


async def lock_version_for_publish(db: AsyncSession, version: FlowDefinitionVersion) -> FlowDefinitionVersion:
    stmt = (select(FlowDefinitionVersion).where(FlowDefinitionVersion.id == version.id)
            .with_for_update().execution_options(populate_existing=True))
    return (await db.execute(stmt)).scalar_one()


def is_seeded_fragment(version: FlowDefinitionVersion) -> bool:
    settings = dict(version.runtime_settings or {})
    return settings.get("seed") == FRAGMENT_SEED_MARKER


def without_seed_markers(settings: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in settings.items() if key not in SEED_KEYS}


def draft_runtime_settings(base: dict[str, Any], definition: dict, composition: dict | None) -> dict[str, Any]:
    # A human's draft never carries the seed marker: it is not shipped code.
    settings = {key: value for key, value in base.items() if key != COMPOSITION_KEY}
    if composition is not None:
        settings[COMPOSITION_KEY] = composition
    if is_fragment(definition):
        settings = without_seed_markers(settings)
    return settings


def report_with_composition(report: dict[str, Any], composition: dict | None) -> dict[str, Any]:
    return report if composition is None else {**report, COMPOSITION_KEY: _summary(composition)}


def composition_view(version: FlowDefinitionVersion) -> dict[str, Any] | None:
    block = composition_of(version)
    if block is None:
        return None
    return {"source": block.get("source"), "fragments": list(block.get("fragments") or []),
            "provenance": dict(block.get("provenance") or {}), "compiled_digest": block.get("compiled_digest")}


def fragment_origin_nodes(version: FlowDefinitionVersion | None) -> frozenset[str]:
    block = composition_of(version)
    return frozenset(dict((block or {}).get("provenance") or {}))


def pinned_source(block: dict[str, Any]) -> dict[str, Any]:
    import copy

    source = copy.deepcopy(block.get("source") or {})
    by_ref = {str(item.get("ref")): item for item in block.get("fragments") or [] if isinstance(item, dict)}
    for node in source.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        pin = by_ref.get(str(node.get("id")))
        config = node.get("config")
        if pin is not None and isinstance(config, dict) and not config.get("fragment_version_id"):
            config["fragment_version_id"] = pin.get("version_id")
    return source


__all__ = [
    "COMPOSITION_KEY",
    "FRAGMENT_SEED_MARKER",
    "compose_for_save",
    "composition_of",
    "composition_view",
    "draft_runtime_settings",
    "fragment_origin_nodes",
    "is_composite",
    "is_fragment",
    "lock_version_for_publish",
    "pinned_source",
    "resolve_fragment_pins",
    "validate_source",
    "verify_composition_at_publish",
]
