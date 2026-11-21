"""The run's environment file is its contract, pinned at preparation.

Without the pin, a run's agent could rewrite ``environment.json`` itself (test and system_test bent, serve and browser
removed) and the platform would judge it against the rewritten file. The file is the law of the run, so:

- **pin**: the first valid account of the run's environment file (the launcher's preparation report, read at the
  run's base) is kept in ``context.contract_pin`` (file, sha256, validated environment, commands). Every reader of the
  contract takes the pin, never the working tree: the run contract's commands (Stop checks, the shell policy, the
  agent's prompt), the device's pipeline and hands-on pass (``environment_pin`` in their views) and the launcher's
  own facts (which commands run outside the sandbox);
- **a change**: a later account with another hash is no contract. It is recorded once (``contract_change_ignored``)
  and the pin stays; only a phase whose node allows it (``config.allow_contract_change: true``, e.g. an onboarding or
  setup story) re-pins, recorded as ``contract_changed`` and flagged for the review (``context.contract_changes``);
- **protection**: the tool policy refuses edits to the pinned file (best effort: a shell can still write it; the pin
  is the guarantee).
"""

from __future__ import annotations

from typing import Any

from ....models import WorkflowRun
from ....time_utils import utc_now

KEY = "contract_pin"
CHANGES_KEY = "contract_changes"
NODE_FLAG = "allow_contract_change"
EVENT_CHANGED = "contract_changed"
EVENT_IGNORED = "contract_change_ignored"


def pin(run: Any) -> dict[str, Any] | None:
    found = dict(dict(getattr(run, "context", None) or {}).get(KEY) or {})
    return found if found.get("sha256") else None


def view(run: Any) -> dict[str, Any] | None:
    """What a device needs to run the pinned contract: the file, its hash and its validated content."""
    found = pin(run)
    return {key: found[key] for key in ("file", "sha256", "environment") if key in found} if found else None


def commands(run: Any) -> dict[str, str] | None:
    found = pin(run)
    return dict(found.get("commands") or {}) if found else None


def _account(report: dict[str, Any]) -> dict[str, Any] | None:
    account = dict(dict(dict(report.get("environment") or {}).get("environment_file") or {}))
    if account.get("state") not in ("ok", "setup_failed") or not account.get("sha256"):
        return None
    return account


async def from_preparation(db: Any, run: WorkflowRun, report: dict[str, Any]) -> None:
    """Pin the first valid account; a later different one re-pins only where the current node allows it."""
    from ..records import record_event
    from .spec import validate_environment

    account = _account(report)
    if account is None:
        return
    environment, errors = validate_environment(account.get("environment")) if account.get("environment") else (
        None, [])
    current = pin(run)
    entry = {"file": str(account.get("file") or ""), "sha256": str(account["sha256"])[:64],
             **({"environment": environment} if environment and not errors else {}),
             "commands": {key: str(value) for key, value in dict(account.get("commands") or {}).items()
                          if key in ("test", "lint", "system_test") and str(value or "").strip()},
             "node_id": run.current_node_id, "at": utc_now().isoformat()}
    if current is None:
        run.context = {**dict(run.context or {}), KEY: entry}
        if environment and environment.get("warnings"):
            # a key this platform does not know is ignored and said, never refused.
            record_event(db, run, "environment_file_warning", node_id=run.current_node_id,
                         detail={"file": entry["file"], "warnings": list(environment["warnings"])[:10]})
        return
    if current["sha256"] == entry["sha256"] or current.get("file") != entry["file"]:
        return
    change = {"from": current["sha256"], "to": entry["sha256"], "file": entry["file"], "node_id": run.current_node_id}
    if await _allowed_here(db, run):
        changes = list(dict(run.context or {}).get(CHANGES_KEY) or [])
        run.context = {**dict(run.context or {}), KEY: entry, CHANGES_KEY: [*changes, change][-20:]}
        record_event(db, run, EVENT_CHANGED, node_id=run.current_node_id, detail=change)
        return
    seen = list(dict(run.context or {}).get("contract_change_seen") or [])
    if entry["sha256"] not in seen:
        run.context = {**dict(run.context or {}), "contract_change_seen": [*seen, entry["sha256"]][-20:]}
        record_event(db, run, EVENT_IGNORED, node_id=run.current_node_id, detail=change)


async def _allowed_here(db: Any, run: WorkflowRun) -> bool:
    from ..graph import graph_for_run

    node = (await graph_for_run(db, run)).nodes.get(str(run.current_node_id or ""))
    return bool(node is not None and dict(node.config or {}).get(NODE_FLAG) is True)


def pin_server_read(run: Any, read: dict[str, Any]) -> None:
    """A server run's first valid read of the file in its working copy becomes the pin (a device's comes from its
    preparation report)."""
    if pin(run) is not None or read.get("state") != "ok" or not read.get("sha256") or not hasattr(run, "context"):
        return
    environment = dict(read.get("environment") or {})
    run.context = {**dict(run.context or {}), KEY: {
        "file": str(read.get("file") or ""), "sha256": str(read["sha256"])[:64], "environment": environment,
        "commands": {key: str(environment.get(key)) for key in ("test", "lint", "system_test")
                     if str(environment.get(key) or "").strip()},
        "node_id": getattr(run, "current_node_id", None), "at": utc_now().isoformat()}}


def changed_from_pin(run: Any, sha256: str) -> bool:
    found = pin(run)
    return bool(found and sha256 and sha256 != found["sha256"])


__all__ = ["CHANGES_KEY", "EVENT_CHANGED", "EVENT_IGNORED", "KEY", "NODE_FLAG", "changed_from_pin", "commands",
           "from_preparation", "pin", "pin_server_read", "view"]
