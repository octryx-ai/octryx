"""One bounded slice of a claimed structured build.

Per layer the slice plans once (:func:`_plan`): it selects the current revisions, retires what the
ledger holds for revisions that are no longer selected (or were extracted under another profile)
and partial revisions that are no longer selected, and extracts the revisions the ledger does not
hold yet, committing after each one. A runner that runs a build slice after slice passes a
:class:`SliceCache`, so the plan (selection and ledger) is made once per claim, not once per slice;
the cache follows what the slices extract. A slice without a cache (the projection worker's one
slice per tick) plans afresh.

The budget is checked before every revision and, while a revision is written, after every insert
batch (``store.write_revision``): a large revision that runs past the deadline stops *partial*
and the next slice resumes it. It stops at ``max_revisions`` revisions or its ``budget_seconds``;
the next slice continues where the ledger says. Every revision write renews the lease fenced on
this worker, in the write's transaction; a slice whose build another worker claimed rolls the write
back and returns :data:`RESULT_LOST`. When every layer is
extracted, the linkage phase (``build_linkage.py``) runs inside the same deadline. When a request
added layers to the build after its linkage started (a manual takeover, ``build.py``), the linkage
restarts, so it covers every requested layer.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_structured import KnowledgeStructuredBuild, KnowledgeStructuredExtraction
from ....time_utils import utc_now
from ..access.authorization import parse_workspace_id
from ..runtime import EvidenceRuntime
from .build_linkage import run_linkage
from .build_states import (
    LEASE_SECONDS,
    MAX_REVISIONS_PER_SLICE,
    RESULT_LOST,
    SLICE_SECONDS,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_RUNNING,
    BuildLease,
    BuildLeaseLostError,
    StructuredSourceError,
)
from .facts import Extraction
from .layers import BuildContext, LayerSpec, layer_specs
from .sources import Candidate
from .store import write_revision
from .store_revisions import partial_revisions, retire_revisions
from .workspace_profile import workspace_profile


@dataclass
class LayerPlan:
    """What a layer still has to extract: the selection, and the ledger as the slices advance it."""

    candidates: list[Candidate]
    done: set[str]
    partial: set[str]


@dataclass
class SliceCache:
    """The layer plans of one claimed build, kept by its runner across the slices of the claim."""

    build_id: str
    layers: dict[str, LayerPlan] = field(default_factory=dict)
    # The profile the plans were made under; another (a Workspace profile saved mid-claim) plans afresh.
    profile_id: str | None = None
    # The layers' memo (``BuildContext.memo``): ``select`` fills it, ``extract`` reads it in later slices.
    memo: dict = field(default_factory=dict)


def _layer_report(report: dict, layer: str) -> dict:
    defaults = {"selected": 0, "extracted": 0, "retired": 0, "failed": 0, "nodes": 0,
                "edges": 0, "removed_nodes": 0, "removed_edges": 0, "warnings": {}}
    entry = report.setdefault("layers", {}).setdefault(layer, {})
    for key, value in defaults.items():
        entry.setdefault(key, value)
    return entry


def _merge_warnings(entry: dict, warnings: Counter | dict) -> None:
    merged = Counter(entry.get("warnings") or {})
    merged.update(dict(warnings))
    entry["warnings"] = dict(sorted(merged.items()))


async def _ledger(db: AsyncSession, project_id: str, layer: str) -> list[tuple[str, str]]:
    rows = await db.execute(
        select(KnowledgeStructuredExtraction.revision_id, KnowledgeStructuredExtraction.profile).where(
            KnowledgeStructuredExtraction.project_id == project_id, KnowledgeStructuredExtraction.layer == layer
        )
    )
    return [(str(row[0]), str(row[1])) for row in rows.all()]


async def _plan(context: BuildContext, spec: LayerSpec, layer: str, entry: dict) -> LayerPlan:
    db, project_id, current = context.db, context.project_id, context.profile.profile_id
    candidates = await spec.select(context)
    selected = {candidate.revision_id for candidate in candidates}
    ledger = await _ledger(db, project_id, layer)
    partial = await partial_revisions(db, project_id=project_id, layer=layer, profile_id=current)
    stale = {revision for revision, owner in ledger if revision not in selected or owner != current}
    stale |= partial - selected
    if stale:
        counts = await retire_revisions(db, project_id=project_id, revision_ids=sorted(stale))
        entry["retired"] += len(stale)
        entry["removed_nodes"] += counts.removed_nodes
        entry["removed_edges"] += counts.removed_edges
        await db.commit()
    done = {revision for revision, owner in ledger if owner == current and revision in selected}
    entry["selected"] = len(selected)
    if "already_current" not in entry:
        # Revisions the ledger already held under this profile when the build first saw the layer.
        entry["already_current"] = len(done)
    return LayerPlan(candidates, done, partial - stale)


@dataclass
class _SliceRun:
    """The state one slice carries from layer to layer: what it writes with and how far it may go."""

    db: AsyncSession
    build: KnowledgeStructuredBuild
    worker_id: str
    context: BuildContext
    lease: BuildLease
    report: dict
    deadline: float
    max_revisions: int
    lease_seconds: float
    claimed_trigger: str | None
    processed: int = 0


_PAUSE = "pause"  # an extraction step's signal: stop the slice and save its progress as running


async def _save(run: _SliceRun, state: str) -> str:
    # Fenced: only while this worker holds the build under the trigger it claimed. A manual
    # takeover changed the trigger: keep the progress, hand the build back now (the runner
    # claims it, with the merged layers). A lost lease (another worker claimed) writes nothing.
    db, build, report = run.db, run.build, run.report
    values: dict = {"report": dict(report), "state": state}
    if state == STATE_RUNNING:
        values["lease_until"] = utc_now() + timedelta(seconds=run.lease_seconds)
    else:
        values["finished_at"] = utc_now()
        values["lease_until"] = None
    held = (KnowledgeStructuredBuild.id == build.id, KnowledgeStructuredBuild.claimed_by == run.worker_id[:120])
    written = await db.execute(
        update(KnowledgeStructuredBuild)
        .where(*held, KnowledgeStructuredBuild.trigger == run.claimed_trigger)
        .values(**values)
    )
    if written.rowcount != 1:
        kept = await db.execute(
            update(KnowledgeStructuredBuild)
            .where(*held, KnowledgeStructuredBuild.state == STATE_RUNNING)
            .values(report=dict(report), lease_until=utc_now())
        )
        state = STATE_RUNNING if kept.rowcount == 1 else RESULT_LOST
    await db.commit()
    return state


async def _extract_one(
    run: _SliceRun, spec: LayerSpec, layer: str, entry: dict, plan: LayerPlan, candidate: Candidate
) -> str | None:
    """Extract and write one revision; ``None`` to go on, else :data:`_PAUSE` or :data:`RESULT_LOST`."""
    try:
        extractor, extraction = await spec.extract(run.context, candidate)
    except StructuredSourceError as error:
        extractor, extraction = f"failed:{error.token}"[:40], Extraction()
        extraction.warn(error.token)
        entry["failed"] += 1
    try:
        counts, complete = await write_revision(
            run.db, project_id=run.build.project_id, revision_id=candidate.revision_id, layer=layer,
            profile_id=run.context.profile.profile_id, extractor=extractor, extraction=extraction,
            resume=candidate.revision_id in plan.partial, deadline=run.deadline, lease=run.lease,
        )
    except BuildLeaseLostError:
        await run.db.rollback()
        return RESULT_LOST
    await run.db.commit()
    run.processed += 1
    entry["nodes"] += counts.nodes
    entry["edges"] += counts.edges
    entry["removed_nodes"] += counts.removed_nodes
    entry["removed_edges"] += counts.removed_edges
    if not complete:
        # Past the deadline inside the revision: the next slice resumes it from what is written.
        plan.partial.add(candidate.revision_id)
        entry["partial_writes"] = int(entry.get("partial_writes", 0)) + 1
        return _PAUSE
    plan.partial.discard(candidate.revision_id)
    plan.done.add(candidate.revision_id)
    entry["extracted"] += 1
    _merge_warnings(entry, extraction.warnings)
    return None


async def _extract_layer(run: _SliceRun, spec: LayerSpec, layer: str, entry: dict, plan: LayerPlan) -> str | None:
    for candidate in plan.candidates:
        if candidate.revision_id in plan.done:
            continue
        if run.processed >= run.max_revisions or time.monotonic() > run.deadline:
            return _PAUSE
        stop = await _extract_one(run, spec, layer, entry, plan, candidate)
        if stop is not None:
            return stop
    return None


async def _layer_plan(
    run: _SliceRun, spec: LayerSpec, layer: str, entry: dict, cache: SliceCache | None, cached: bool
) -> LayerPlan:
    plan = cache.layers.get(layer) if cached else None
    if plan is None:
        plan = await _plan(run.context, spec, layer, entry)
        if cached:
            cache.layers[layer] = plan
    return plan


async def _link_and_finish(run: _SliceRun, specs: dict) -> str:
    build, report = run.build, run.report
    if report.get("linked_layers") not in (None, list(build.layers)):
        report["linkage"] = {}  # layers were added after the linkage started: link them all again
    report["linked_layers"] = list(build.layers)
    # A rebuilt manual changes what configuration settings link to, so that linkage reruns too.
    if not await run_linkage(run.context, build=build, report=report, specs=specs, deadline=run.deadline):
        return await _save(run, STATE_RUNNING)
    started = build.started_at
    report["duration_seconds"] = round((utc_now() - started).total_seconds(), 1) if started else None
    return await _save(run, STATE_COMPLETED)


async def run_build_slice(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime | None,
    build_id: str,
    worker_id: str,
    budget_seconds: float = SLICE_SECONDS,
    max_revisions: int = MAX_REVISIONS_PER_SLICE,
    lease_seconds: float = LEASE_SECONDS,
    cache: SliceCache | None = None,
) -> str:
    """Run one bounded slice of a claimed build; returns the build's state afterwards.

    :data:`RESULT_LOST` when another worker holds the build (it claimed it after this worker's lease
    expired): nothing is written, and the caller stops working on the build.
    """
    # The claim is a conditional UPDATE; never trust an identity-map copy from before it.
    build = await db.get(KnowledgeStructuredBuild, build_id, populate_existing=True)
    if build is None:
        return STATE_FAILED
    if build.state != STATE_RUNNING:
        return build.state
    if build.claimed_by != worker_id[:120]:
        return RESULT_LOST
    lease = BuildLease(build.id, worker_id, lease_seconds)
    profile = await workspace_profile(db, build.project_id)
    cached = cache is not None and cache.build_id == build.id
    if cached and cache.profile_id != profile.profile_id:
        cache.layers.clear()
        cache.memo.clear()
        cache.profile_id = profile.profile_id
    context = BuildContext(db, runtime, parse_workspace_id(build.project_id), build.project_id, profile,
                           memo=cache.memo if cached else {})
    report = dict(build.report or {})
    report["profile"] = profile.profile_id
    report["slices"] = int(report.get("slices", 0)) + 1
    if build.started_at is None:
        build.started_at = utc_now()
    specs = layer_specs()
    run = _SliceRun(db, build, worker_id, context, lease, report, time.monotonic() + budget_seconds,
                    max_revisions, lease_seconds, build.trigger)
    for layer in build.layers:
        spec = specs.get(layer)
        if spec is None:
            report.setdefault("layers", {})[layer] = {"state": "not_available"}
            continue
        entry = _layer_report(report, layer)
        plan = await _layer_plan(run, spec, layer, entry, cache, cached)
        stop = await _extract_layer(run, spec, layer, entry, plan)
        if stop == RESULT_LOST:
            return RESULT_LOST
        if stop is not None:
            return await _save(run, STATE_RUNNING)
    return await _link_and_finish(run, specs)


__all__ = ["LayerPlan", "SliceCache", "run_build_slice"]
