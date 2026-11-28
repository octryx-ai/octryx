"""What would this policy block?"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import IdentityGroup, Role, User, UserGroup, UserRole
from . import catalog
from .bench_question import BenchError, parse_question
from .builder import render
from .builder_content import is_content_policy
from .builder_model import PolicyModel
from .entity_listing import LOG_TOOLS_BY_ARGUMENT, list_entities, tool_items
from .policy_text import index_statements, join_statements, split_statements
from .policy_view import working_version
from .principals import ADMIN_ROLE
from .test_bench import CustomText, ask
from .test_cases import run_cases

KIND_BLOCK = "block"
KIND_CONTROL = "control"
CONTROL_COMMAND = "git status"
CONTROL_PATH = "/workspace/README.md"
EXAMPLE_ALIAS = "example-model"
UNPARSEABLE_COMMAND = 'echo "unterminated'
MAX_BLOCKS = 3


def _levels_ok(model: PolicyModel, classification: str | None) -> bool:
    where = model.where
    levels = catalog.classification_levels()
    if where.unclassified and classification:
        return False
    if where.classification_is and classification not in where.classification_is:
        return False
    if where.classification_at_least and (not classification or levels.index(classification)
                                          < levels.index(where.classification_at_least)):
        return False
    return True


async def _workspace(db: AsyncSession, model: PolicyModel) -> dict[str, Any] | None:
    workspaces = (await list_entities(db, types=["workspaces"]))["workspaces"]
    if model.where.workspaces:
        chosen = [item for item in workspaces if item["id"] in model.where.workspaces]
    else:
        chosen = [item for item in workspaces if _levels_ok(model, item["classification"])]
    return chosen[0] if chosen else None


async def _admins(db: AsyncSession) -> set[str]:
    stmt = select(UserRole.user_id).join(Role, Role.id == UserRole.role_id).where(Role.name == ADMIN_ROLE)
    return {str(item) for item in (await db.execute(stmt)).scalars()}


async def _principal(db: AsyncSession, model: PolicyModel) -> str | None:
    who = model.who
    if who.mode == "users":
        candidates = list(who.items)
    elif who.mode == "roles":
        stmt = (select(UserRole.user_id).join(Role, Role.id == UserRole.role_id).join(User, User.id == UserRole.user_id)
                .where(Role.name.in_(who.items), User.is_active.is_(True)).order_by(UserRole.user_id))
        candidates = [str(item) for item in (await db.execute(stmt)).scalars()]
    elif who.mode == "groups":
        stmt = (select(UserGroup.user_id).join(IdentityGroup, IdentityGroup.id == UserGroup.group_id)
                .join(User, User.id == UserGroup.user_id)
                .where(IdentityGroup.name.in_(who.items), User.is_active.is_(True)).order_by(UserGroup.user_id))
        candidates = [str(item) for item in (await db.execute(stmt)).scalars()]
    elif who.except_admins:
        stmt = select(User.id).where(User.is_active.is_(True)).order_by(User.username)
        candidates = [str(item) for item in (await db.execute(stmt)).scalars()]
    else:
        return None
    if who.except_admins:
        admins = await _admins(db)
        candidates = [item for item in candidates if item not in admins]
    return candidates[0] if candidates else None


def _tool(model: PolicyModel, *, writes: bool | None = None, logs: bool | None = None,
          connector: bool = True) -> str | None:
    families = set(model.what.families)
    for tool in tool_items():
        family = tool["connector_family"]
        if tool["name"] in LOG_TOOLS_BY_ARGUMENT or bool(family) != connector:
            continue
        if connector and ((model.what.tools and tool["name"] not in model.what.tools)
                          or (families and family not in families)):
            continue
        if writes is not None and tool["mutates_state"] != writes:
            continue
        if logs is not None and tool["reads_logs"] != logs:
            continue
        return tool["name"]
    return None


def _question(name: str, kind: str, workspace: str, user: str | None, action: str, resource: dict) -> dict[str, Any]:
    request = {"workspace_id": workspace, "user_id": user, "action": action, "resource": resource}
    return {"name": name, "kind": kind, "expected": "deny" if kind == KIND_BLOCK else "allow", "request": request}


def _connections(model: PolicyModel) -> dict[str, Any]:
    return {"connections": [model.where.connections[0]]} if model.where.connections else {}


def _tool_questions(model: PolicyModel, ws: str, user: str | None) -> list[dict[str, Any]]:
    actions = set(model.actions)
    action = next(item for item in ("write_connector", "read_connector", "call_tool") if item in actions)
    logs = True if model.what.reads_logs else None
    if action == "call_tool":
        tool = model.what.tools[0] if model.what.tools else _tool(model, logs=logs, connector=False)
    else:
        tool = _tool(model, writes=action == "write_connector", logs=logs)
    if not tool:
        return []
    blocked = _question(f"{tool} is blocked", KIND_BLOCK, ws, user, action, {"tool": tool, **_connections(model)})
    control = None
    if action == "write_connector" and model.where.connections:
        control = _question(f"{tool} on another connection stays allowed", KIND_CONTROL, ws, user, action,
                            {"tool": tool, "connections": ["policy-example-other-connection"]})
    elif action == "write_connector" and "read_connector" not in actions:
        reader = _tool(model, writes=False, logs=False if logs else None)
        if reader:
            control = _question(f"{reader} (a read) stays allowed", KIND_CONTROL, ws, user, "read_connector",
                                {"tool": reader, **_connections(model)})
    elif "call_tool" not in actions:
        generic = _tool(model, connector=False)
        if generic:
            control = _question(f"{generic} stays allowed", KIND_CONTROL, ws, user, "call_tool", {"tool": generic})
    return [blocked, *([control] if control else [])]


async def _model_questions(db: AsyncSession, model: PolicyModel, ws: str, user: str | None) -> list[dict[str, Any]]:
    aliases = [item["alias"] for item in (await list_entities(db, types=["model_aliases"]))["model_aliases"]]
    listed = set(model.what.models)
    outside = next((alias for alias in aliases if alias not in listed), EXAMPLE_ALIAS)
    if model.what.model_mode == "only" and model.what.models:
        blocked_alias, allowed_alias = model.what.models[0], outside
    else:
        blocked_alias, allowed_alias = outside, (model.what.models[0] if model.what.models else None)
    found = [_question(f"{blocked_alias} is blocked", KIND_BLOCK, ws, user, "call_model", {"alias": blocked_alias})]
    if allowed_alias:
        found.append(_question(f"{allowed_alias} stays allowed", KIND_CONTROL, ws, user, "call_model",
                               {"alias": allowed_alias}))
    return found


def _command(model: PolicyModel) -> str:
    what = model.what
    if what.prefixes:
        return f"{what.prefixes[0]} example"
    parts = [what.programs[0] if what.programs else "example-tool", *what.arguments]
    if what.option_values:
        parts.append(what.option_values[0])
    return " ".join(parts)


def _command_questions(model: PolicyModel, ws: str, user: str | None) -> list[dict[str, Any]]:
    unparseable_only = model.what.unparseable and not (model.what.prefixes or model.what.programs)
    command = UNPARSEABLE_COMMAND if unparseable_only else _command(model)
    found = [_question(f"{command} is blocked", KIND_BLOCK, ws, user, "run_command", {"command": command})]
    if model.conditions.unless_option_values:
        allowed = f"{command} {model.conditions.unless_option_values[0]}"
        found.append(_question(f"{allowed} stays allowed", KIND_CONTROL, ws, user, "run_command", {"command": allowed}))
    else:
        found.append(_question(f"{CONTROL_COMMAND} stays allowed", KIND_CONTROL, ws, user, "run_command",
                               {"command": CONTROL_COMMAND}))
    return found


def _path_questions(model: PolicyModel, ws: str, user: str | None) -> list[dict[str, Any]]:
    action = "read_path" if "read_path" in model.actions else "write_path"
    tool = "Read" if action == "read_path" else "Edit"
    pattern = model.what.paths[0] if model.what.paths else "*example*"
    path = pattern.replace("*", "example")
    path = path if path.startswith("/") else f"/workspace/{path}"
    return [_question(f"{tool} {path} is blocked", KIND_BLOCK, ws, user, action, {"path": path, "tool": tool}),
            _question(f"{tool} {CONTROL_PATH} stays allowed", KIND_CONTROL, ws, user, action,
                      {"path": CONTROL_PATH, "tool": tool})]


def _remote_questions(model: PolicyModel, ws: str, user: str | None) -> list[dict[str, Any]]:
    action = "use_remote_embeddings" if "use_remote_embeddings" in model.actions else "use_reranker"
    classes = catalog.data_policy_classes()
    limit = model.what.remote_class_below
    blocked = classes[0] if limit else classes[-1]
    found = [_question(f"a remote model of class {blocked} is blocked", KIND_BLOCK, ws, user, action,
                       {"data_policy_class": blocked})]
    if limit:
        found.append(_question(f"a remote model of class {limit} stays allowed", KIND_CONTROL, ws, user, action,
                               {"data_policy_class": limit}))
    return found


async def generate(db: AsyncSession, model: PolicyModel) -> dict[str, Any]:
    workspace = await _workspace(db, model)
    notes: list[str] = []
    if workspace is None:
        return {"workspace": None, "user_id": None, "examples": [],
                "notes": ["No active Workspace matches the where-part, so there is nothing to ask."]}
    user = await _principal(db, model)
    if model.who.mode != "everyone" and user is None:
        notes.append("Nobody matches the who-part yet; the examples run without a user.")
    ws = workspace["id"]
    if is_content_policy(model):  # the bench asks without content; an alias question would mislead
        notes.append("This policy decides on what the content scan finds; the test bench cannot ask with a scan "
                     "result yet, so there are no generated examples. The saved test cases still run.")
        return {"workspace": workspace, "user_id": user, "examples": [], "notes": notes}
    groups: list[list[dict[str, Any]]] = []
    actions = set(model.actions)
    if actions & {"write_connector", "read_connector", "call_tool"}:
        groups.append(_tool_questions(model, ws, user))
        if not groups[-1]:
            notes.append("No tool with fixed facts matches the chosen connectors and tools, so there is no tool "
                         "example; ask the test bench with a concrete tool.")
    if "call_model" in actions:
        groups.append(await _model_questions(db, model, ws, user))
    if "run_command" in actions:
        groups.append(_command_questions(model, ws, user))
    if actions & {"read_path", "write_path"}:
        groups.append(_path_questions(model, ws, user))
    if actions & {"use_remote_embeddings", "use_reranker"}:
        groups.append(_remote_questions(model, ws, user))
    if "use_seat" in actions:
        groups.append([_question("a personal seat is blocked", KIND_BLOCK, ws, user, "use_seat", {})])
    blocks = [item for group in groups for item in group if item["kind"] == KIND_BLOCK][:MAX_BLOCKS]
    control = next((item for group in groups for item in group if item["kind"] == KIND_CONTROL), None)
    return {"workspace": workspace, "user_id": user, "examples": blocks + ([control] if control else []),
            "notes": notes}


async def candidate_text(db: AsyncSession, model: PolicyModel, original_id: str | None) -> CustomText:
    row = await working_version(db)
    text = str(row.policies_text or "") if row is not None else ""
    split = split_statements(text)
    statements = [(item.policy_id, item.text) for item in index_statements(text)] if split.statements else []
    replaced = {original_id or model.id, model.id}
    kept = [(policy_id, statement) for policy_id, statement in statements if policy_id not in replaced]
    label = f"version {row.version} with this policy" if row is not None else "this policy alone"
    return CustomText(join_statements([*kept, (model.id, render(model))], split.trailer), label)


async def impact(db: AsyncSession, model: PolicyModel, original_id: str | None = None) -> dict[str, Any]:
    generated = await generate(db, model)
    candidate = await candidate_text(db, model, original_id)
    examples = []
    for example in generated["examples"]:
        try:
            answer = await ask(db, parse_question(example["request"]), candidate)
            determining = [item["id"] for item in answer["determining"]]
            result = {"decision": answer["decision"], "determining": determining, "error": None,
                      "legacy": answer["legacy"], "notes": answer["notes"]}
        except BenchError as error:
            result = {"decision": "error", "determining": [], "error": error.code, "legacy": None, "notes": []}
        by_policy = model.id in result["determining"]
        result["by_this_policy"] = by_policy
        result["as_expected"] = by_policy if example["kind"] == KIND_BLOCK else not by_policy
        examples.append({**example, "answer": result})
    return {"workspace": generated["workspace"], "user_id": generated["user_id"], "notes": generated["notes"],
            "policy_source": candidate.label, "examples": examples, "cases": await run_cases(db, candidate)}


__all__ = ["KIND_BLOCK", "KIND_CONTROL", "candidate_text", "generate", "impact"]
