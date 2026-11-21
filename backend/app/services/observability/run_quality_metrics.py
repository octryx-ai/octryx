"""Whether runs finish without a person, how they prove their result and where they lose time.

All counted in this process at the event, never through the database:

- ``octryx_run_interventions_total{workflow,size_class,workflow_version,action}``: a person acted on a run (an
  action of ``workflow_runs.actions.perform_action``, a handover or an emergency stop);
- ``octryx_pipeline_red_before_total{workflow,result}``: per pipeline report, whether the tests that must fail on the
  base did (``proven``), did not (``unproven``) or none were asked for (``not_required``);
- ``octryx_pipeline_skipped_total{workflow}``: commands the device did not start because a cheaper one before them
  was red (fail fast);
- ``octryx_stop_not_done_total{workflow,check}``: a run phase's Stop refused as not done, by the failed check's type;
- ``octryx_device_wait_seconds{engine}``: from a device job's creation to its device accepting the turn;
- ``octryx_device_reconnects_total``: a device connected again while its previous connection was still attached;
- ``octryx_devices_online``: devices connected to this process (API only; rendered from the hub at the scrape).

``prompt_version`` is a short hash of the platform's prompt catalog seeds: one value per build, so a change of the
platform's texts shows as a new label value on the run histograms (``maintenance_metrics``).
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from functools import lru_cache
from typing import Any

from .metric_types import Counter, Gauge, Histogram, _Metric

WAIT_SECONDS = (1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600)
_REMEMBERED = 4000

INTERVENTIONS = Counter("octryx_run_interventions_total", "A person acted on a run (continue, change the plan, abort,"
                        " take over, retry, handover, emergency stop ...) by workflow, start size class, workflow"
                        " version and action", ("workflow", "size_class", "workflow_version", "action"))
RED_BEFORE = Counter("octryx_pipeline_red_before_total", "Pipeline reports by workflow and red-before result"
                     " (proven, unproven, not_required)", ("workflow", "result"))
PIPELINE_SKIPPED = Counter("octryx_pipeline_skipped_total", "Pipeline commands not started because an earlier check"
                           " was red (fail fast), by workflow", ("workflow",))
STOP_NOT_DONE = Counter("octryx_stop_not_done_total", "Run phase Stops refused as not done, by workflow and failed"
                        " check type", ("workflow", "check"))
DEVICE_WAIT = Histogram("octryx_device_wait_seconds", "Seconds from a device job's creation to its device accepting"
                        " the turn, by engine", ("engine",), WAIT_SECONDS)
DEVICE_RECONNECTS = Counter("octryx_device_reconnects_total", "Device connections that replaced a still attached one"
                            " (a reconnect)", ())
DEVICES_ONLINE = Gauge("octryx_devices_online", "Devices connected to this API process", ())

METRICS: tuple[_Metric, ...] = (INTERVENTIONS, RED_BEFORE, PIPELINE_SKIPPED, STOP_NOT_DONE, DEVICE_WAIT,
                                DEVICE_RECONNECTS)

_QUEUED: OrderedDict[str, float] = OrderedDict()  # device job id -> monotonic seconds at its creation


@lru_cache(maxsize=1)
def prompt_version() -> str:
    """Short hash of the prompt catalog's seed texts (key and text, in catalog order)."""
    from ..prompt_catalog.seeds import all_seed_specs

    digest = hashlib.sha256()
    for spec in all_seed_specs():
        digest.update(f"{spec.key}\0{spec.seed}\0".encode())
    return digest.hexdigest()[:8]


def _size_class(run: Any) -> str:
    from .maintenance_metrics import _context

    entry = dict(_context(run).get("size_class") or {})
    return str(entry.get("initial") or entry.get("class") or "none")


def intervention(db: Any, run: Any, action: str) -> None:
    """A person's action on ``run`` (the run row in memory), counted when ``db``'s transaction commits."""
    from .agent_metrics import on_commit

    labels = {"workflow": str(getattr(run, "workflow_key", "") or "unknown"), "size_class": _size_class(run),
              "workflow_version": str(getattr(run, "workflow_version", "") or "none"), "action": action or "unknown"}
    on_commit(db, lambda: INTERVENTIONS.inc(**labels))


def pipeline_reported(workflow: str, detail: dict[str, Any]) -> None:
    """Red-before result and fail-fast skips of one ``pipeline_reported`` event."""
    unproven = detail.get("unproven")
    result = "not_required" if unproven is None else "unproven" if unproven else "proven"
    RED_BEFORE.inc(workflow=workflow, result=result)
    commands = detail.get("commands") if isinstance(detail.get("commands"), list) else []
    skipped = sum(1 for item in commands if isinstance(item, dict) and item.get("skipped"))
    if skipped:
        PIPELINE_SKIPPED.inc(skipped, workflow=workflow)


def stop_not_done(workflow: str, failed: list[Any]) -> None:
    """A Stop refused as not done: one count per failed blocking check, by its type."""
    for result in failed:
        STOP_NOT_DONE.inc(workflow=workflow or "unknown", check=str(getattr(result, "type", "") or "unknown"))


def job_queued(job_id: str) -> None:
    _QUEUED[job_id] = time.monotonic()
    while len(_QUEUED) > _REMEMBERED:
        _QUEUED.popitem(last=False)


def job_accepted(job_id: str, engine: str) -> None:
    """The device accepted the job's first turn: the wait since its creation (in this process) is observed once."""
    queued = _QUEUED.pop(job_id, None)
    if queued is not None:
        DEVICE_WAIT.observe(max(0.0, time.monotonic() - queued), engine=engine)


def device_reconnected() -> None:
    DEVICE_RECONNECTS.inc()


def online_lines(hub: Any) -> list[str]:
    """``octryx_devices_online`` from the hub's attached, healthy connections (memory only)."""
    connections = getattr(hub, "_connections", {}) or {}
    DEVICES_ONLINE.series.clear()
    DEVICES_ONLINE.set(sum(1 for device_id in list(connections) if hub.connected(device_id)))
    return DEVICES_ONLINE.render()


def reset() -> None:
    for metric in (*METRICS, DEVICES_ONLINE):
        metric.series.clear()
    _QUEUED.clear()


__all__ = ["METRICS", "device_reconnected", "intervention", "job_accepted", "job_queued", "online_lines",
           "pipeline_reported", "prompt_version", "reset", "stop_not_done"]
