"""The model of a workflow run's own seat turn, by the phase's model class (to save cost, the phase pins in the seeds
are defaults people can change)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

INSTALLATION_KEY = "seat_models"
WORKSPACE_KEY = "seat_models"
NODE_CLASS_KEY = "model_class"
WORKFLOW_MODELS_KEY = "models"
CONTEXT_KEY = "seat_model"
EVENT_CHOSEN = "run_turn_model"
SOURCE_NODE = "node"
SOURCE_RUN_START = "run_start"
SOURCE_THREAD = "thread"
SOURCE_WORKFLOW = "workflow"
SOURCE_WORKSPACE = "workspace"
SOURCE_INSTALLATION = "installation"
SOURCE_DEVICE = "device"
MAX_MODEL_CHARS = 120
EXPLICIT_SOURCES = (SOURCE_NODE, SOURCE_RUN_START, SOURCE_THREAD)


@lru_cache(maxsize=1)
def _file() -> dict[str, Any]:
    return json.loads(Path(__file__).with_name("seat_models.json").read_text(encoding="utf-8"))


def classes() -> tuple[str, ...]:
    return tuple(_file()["classes"])


def shipped_defaults() -> dict[str, str]:
    return dict(_file()["installation_defaults"])


def class_models(value: Any) -> dict[str, str]:
    known = set(classes())
    if not isinstance(value, dict):
        return {}
    return {str(key): item.strip() for key, item in value.items()
            if key in known and isinstance(item, str) and item.strip() and len(item) <= MAX_MODEL_CHARS}


def node_class(config: dict[str, Any], capability_class: str = "") -> str:
    own = str(dict(config or {}).get(NODE_CLASS_KEY) or "").strip()
    if own in classes():
        return own
    return str(_file()["class_of_capability"].get(capability_class or "read_only") or "implement")


@dataclass(frozen=True)
class Levels:
    workflow: dict[str, str] = field(default_factory=dict)
    workspace: dict[str, str] = field(default_factory=dict)
    installation: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Choice:
    model: str
    source: str
    model_class: str

    def message(self) -> str:
        from ..run_texts import run_text

        label = str(_file()["source_labels"].get(self.source) or self.source).format(model_class=self.model_class)
        return run_text("model.chosen", model=self.model or "(device default)", source=label)


def _fits(model: str, engine: str) -> bool:
    # A Codex seat never gets a Claude model.
    from ...agent_gateway.review_keys import model_family

    family = model_family(model)
    return not engine or family is None or family == engine


def choose(levels: Levels, config: dict[str, Any], *, capability_class: str = "", run_model: str = "",
           thread_model: str = "", engine: str = "") -> Choice:
    config = dict(config or {})
    model_class = node_class(config, capability_class)
    ranked = (
        (str(config.get("model") or "").strip(), SOURCE_NODE),
        (str(run_model or "").strip(), SOURCE_RUN_START),
        (str(thread_model or "").strip(), SOURCE_THREAD),
        (levels.workflow.get(model_class, ""), SOURCE_WORKFLOW),
        (levels.workspace.get(model_class, ""), SOURCE_WORKSPACE),
        (levels.installation.get(model_class, ""), SOURCE_INSTALLATION),
    )
    for model, source in ranked:
        if model and (source in EXPLICIT_SOURCES or _fits(model, engine)):
            return Choice(model=model, source=source, model_class=model_class)
    return Choice(model="", source=SOURCE_DEVICE, model_class=model_class)


async def installation_models(db: Any) -> dict[str, str]:
    from ...system_config.values import get_system_config_value

    raw = await get_system_config_value(db, INSTALLATION_KEY)
    try:
        stored = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        stored = {}
    return {**shipped_defaults(), **class_models(stored)}


async def levels_for(db: Any, run: Any) -> Levels:
    from ....models import FlowDefinitionVersion
    from ...agent_gateway.policy import load_workspace_policy
    from ...devices.device_runs_keys import device_runs_section

    version = await db.get(FlowDefinitionVersion, run.flow_definition_version_id or "") \
        if getattr(run, "flow_definition_version_id", None) else None
    workflow = class_models(dict(getattr(version, "definition_json", None) or {}).get(WORKFLOW_MODELS_KEY))
    workspace: dict[str, str] = {}
    if getattr(run, "project_id", None):
        loaded = await load_workspace_policy(db, run.project_id)
        if loaded.policy is not None:
            workspace = class_models(device_runs_section(loaded.policy.raw).get(WORKSPACE_KEY))
    return Levels(workflow=workflow, workspace=workspace, installation=await installation_models(db))


def run_start_model(run: Any) -> str:
    from ..runtime_target.target import stored_target

    return str(dict(stored_target(run) or {}).get("model") or "").strip()


async def seat_choice(db: Any, run: Any, node: Any, thread_model: str = "") -> Choice:
    from ..graph import NODE_PHASE
    from ..phase_contract import phase_definition
    from ..review.choice import run_engine

    config = dict(getattr(node, "config", None) or {})
    contract = dict(phase_definition(run, node).get("workflow_contract") or {}) if node.kind == NODE_PHASE else {}
    if thread_model and thread_model in class_default_models(run):
        # A class default an earlier phase ran is the platform's choice, not a person's, though a turn writes its model
        # onto the thread.
        thread_model = ""
    return choose(await levels_for(db, run), config, capability_class=str(contract.get("capability_class") or ""),
                  run_model=run_start_model(run), thread_model=thread_model, engine=await run_engine(db, run))


def class_default_models(run: Any) -> set[str]:
    seen = dict(dict(getattr(run, "context", None) or {}).get(CONTEXT_KEY) or {})
    return {str(entry[0]) for entry in seen.values() if isinstance(entry, list) and len(entry) > 1 and entry[0]
            and entry[1] in (SOURCE_WORKFLOW, SOURCE_WORKSPACE, SOURCE_INSTALLATION)}


def note_choice(db: Any, run: Any, node_id: str, choice: Choice) -> None:
    from ..records import record_event

    context = dict(run.context or {})
    seen = dict(context.get(CONTEXT_KEY) or {})
    key = [choice.model, choice.source, choice.model_class]
    if seen.get(node_id) == key:
        return
    run.context = {**context, CONTEXT_KEY: {**seen, node_id: key}}
    record_event(db, run, EVENT_CHOSEN, node_id=node_id, detail={
        "model": choice.model, "source": choice.source, "class": choice.model_class, "message": choice.message()})


def chose_class_default(run: Any, node_id: str) -> bool:
    seen = dict(dict(run.context or {}).get(CONTEXT_KEY) or {}).get(node_id)
    return isinstance(seen, list) and len(seen) > 1 and seen[1] in (SOURCE_WORKFLOW, SOURCE_WORKSPACE,
                                                                     SOURCE_INSTALLATION)


__all__ = ["CONTEXT_KEY", "EVENT_CHOSEN", "INSTALLATION_KEY", "Choice", "Levels", "choose", "chose_class_default",
           "class_default_models", "class_models", "classes", "installation_models", "levels_for", "node_class",
           "note_choice", "seat_choice"]
