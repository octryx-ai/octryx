"""Every production driver call carries its scope: a resolved Workspace or an explicit platform scope."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import app.services.content_security.model_call_outcome as model_call_module
import app.services.content_security.model_call_scope as model_call_scope_module
from app.services.content_security.handling import PlatformScope, plan_for
from app.services.content_security.model_call_scope import (
    ModelCallScopeMissingError,
    model_call_scope,
    platform_call,
    session_call,
    workspace_call,
)
from app.services.content_security.refusal import ContentPolicyRefusedError
from tests.content_security.model_call_driver_support import DIRECT, DRIVERS, Reply
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

APP = Path(__file__).resolve().parents[2] / "app"
#: The provider drivers themselves: a chat nested in another driver's chat is the same (outer, scoped) request.
DRIVER_PACKAGE = "agent/providers/"
CHAIN_NAMES = frozenset({"_chat_with_runtime_fallback", "_chat_with_runtime_fallback_impl", "chat_func"})
INJECTED_NAME = "chat_with_runtime_fallback"

#: (module, enclosing function, call) → why the scope is set by the caller of this site, not here.
PASS_THROUGH: dict[tuple[str, str, str], str] = {
    ("agent/runtime/runtime_fallback.py", "_FallbackChain._call", "client.chat"):
        "the runtime chain itself; every call of the chain is checked",
}


def _scope_with(node: ast.AST) -> bool:
    return isinstance(node, ast.With | ast.AsyncWith) and any(
        isinstance(item.context_expr, ast.Call) and _name(item.context_expr.func) == "model_call_scope"
        for item in node.items)


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _dispatch(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr == "chat":
        return ast.unparse(func)
    name = _name(func)
    return name if name in CHAIN_NAMES or name == INJECTED_NAME else ""


class _Sites(ast.NodeVisitor):
    def __init__(self) -> None:
        self.stack: list[str] = []
        self.scoped: list[bool] = [False]
        self.calls: list[tuple[str, str, bool, int]] = []
        self.injected: list[tuple[str, int]] = []
        self.scoping_functions: set[str] = set()

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        self.stack.append(node.name)
        self.scoped.append(False)  # a nested definition does not inherit an enclosing scope
        self.generic_visit(node)
        self.scoped.pop()
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802 - ast.NodeVisitor protocol
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802 - ast.NodeVisitor protocol
        self._function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802 - ast.NodeVisitor protocol
        self._function(node)

    def _with(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item)
        if _scope_with(node):
            self.scoping_functions.add(".".join(self.stack))
        self.scoped.append(self.scoped[-1] or _scope_with(node))
        for statement in node.body:
            self.visit(statement)
        self.scoped.pop()

    def visit_With(self, node: ast.With) -> None:  # noqa: N802 - ast.NodeVisitor protocol
        self._with(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:  # noqa: N802 - ast.NodeVisitor protocol
        self._with(node)

    def visit_Call(self, node: ast.Call) -> None:
        dispatch = _dispatch(node)
        if dispatch:
            self.calls.append((".".join(self.stack), dispatch, self.scoped[-1], node.lineno))
        for keyword in node.keywords:
            if keyword.arg == INJECTED_NAME:
                self.injected.append((ast.unparse(keyword.value), node.lineno))
        self.generic_visit(node)


def scan(source: str) -> _Sites:
    sites = _Sites()
    sites.visit(ast.parse(source))
    return sites


def _app_sites() -> dict[str, _Sites]:
    return {path.relative_to(APP).as_posix(): scan(path.read_text(encoding="utf-8"))
            for path in sorted(APP.rglob("*.py")) if "static" not in path.parts}


def _function_names(qualname: str) -> set[str]:
    return {qualname, qualname.rsplit(".", 1)[-1]}


def test_every_production_dispatch_sets_a_model_call_scope():
    unscoped, passed, scoped = [], set(), 0
    for module, sites in _app_sites().items():
        if module.startswith(DRIVER_PACKAGE):
            continue
        for function, dispatch, inside, line in sites.calls:
            key = next((key for key in PASS_THROUGH if key[0] == module and key[2] == dispatch
                        and key[1] in _function_names(function)), None)
            if inside:
                scoped += 1
            elif key is not None:
                passed.add(key)
            else:
                unscoped.append(f"{module}:{line} {function}: {dispatch}")
    assert unscoped == [], "a driver call without `with model_call_scope(...)`: set the resolved Workspace scope"
    assert passed == set(PASS_THROUGH), "a pass-through that no longer exists must leave PASS_THROUGH"
    assert scoped >= 13, "the scoped production dispatch sites (B-01 inventory, less the deleted loop's two)"


def test_no_chain_is_injected_into_a_dispatch():
    # The injected runtime chain belonged to the platform loop (WP-C4b1): every dispatch calls its own chain.
    assert {(module, value) for module, sites in _app_sites().items() for value, _line in sites.injected} == set()


@pytest.mark.parametrize("source", [
    "async def answer(client):\n    return await client.chat(messages=[], model='m')\n",
    "async def answer(client):\n    result = await asyncio.wait_for(\n        client.chat(messages=[]), timeout=3)\n",
    "async def answer(get):\n    return await get().chat(messages=[])\n",
    "async def plan(runtimes):\n    return await _chat_with_runtime_fallback(runtimes, messages=[])\n",
    "async def plan(chat_func):\n    return await chat_func([], messages=[])\n",
    # A nested function does not inherit the enclosing scope: it can run after the scope ended.
    "async def outer(client):\n    with model_call_scope(scope):\n        async def later():\n"
    "            return await client.chat(messages=[])\n    return later\n",
    "async def answer(client):\n    with prompt_set_scope(s):\n        return await client.chat(messages=[])\n",
])
def test_the_detector_reports_an_unscoped_dispatch(source):
    (call,) = scan(source).calls
    assert call[2] is False


@pytest.mark.parametrize("source", [
    "async def answer(client):\n    with model_call_scope(scope):\n        return await client.chat(messages=[])\n",
    "async def answer(client):\n    with model_call_scope(workspace_call(ws)), other():\n"
    "        try:\n            return await client.chat(messages=[])\n        finally:\n            pass\n",
    "async def plan(chat_func):\n    with model_call_scope(scope):\n        return await chat_func([], messages=[])\n",
])
def test_the_detector_accepts_a_scoped_dispatch(source):
    (call,) = scan(source).calls
    assert call[2] is True


def test_the_detector_ignores_what_is_not_a_dispatch():
    source = ("class Client:\n    async def chat(self, messages):\n        '''client.chat(...)'''\n"
              "        return messages  # client.chat(messages)\n"
              "def other(x):\n    return x.chat_history()\n")
    assert scan(source).calls == []


@pytest.mark.parametrize("driver_name", sorted(DRIVERS))
async def test_an_unscoped_driver_call_is_refused_before_anything_is_sent(driver_name, monkeypatch):
    entries: list[dict] = []
    monkeypatch.setattr(model_call_module, "record_decision", entries.append)
    harness = DRIVERS[driver_name](monkeypatch, Reply("ok"))
    try:
        with pytest.raises(ModelCallScopeMissingError) as refused:
            await harness.driver.chat(messages=[{"role": "user", "content": "hello"}], model=harness.model)
    finally:
        await harness.driver.close()
    assert harness.sent() == [], "nothing reaches the provider"
    assert isinstance(refused.value, ContentPolicyRefusedError), "a content refusal: no runtime fallback"
    assert refused.value.content_notice["reason"] == "content_handling_scope_missing"
    (entry,) = entries
    assert entry["outcome"] == "denied" and entry["workspace_id"] is None
    assert refused.value.content_notice["decision_id"] == entry["id"]


def test_a_scope_names_a_workspace_or_a_known_platform_reason():
    with pytest.raises(ModelCallScopeMissingError):
        workspace_call("  ")
    with pytest.raises(ModelCallScopeMissingError):
        workspace_call([])
    with pytest.raises(ValueError):
        platform_call("because")
    assert workspace_call(["ws-1", " ws-1 ", "ws-2"]).workspace_ids == ("ws-1", "ws-2")
    assert session_call(None).platform == PlatformScope("session_without_workspace")
    assert session_call("ws-1", session_id="s").workspace_ids == ("ws-1",)
    with pytest.raises(ModelCallScopeMissingError):
        with model_call_scope(None):  # type: ignore[arg-type]
            pass


async def test_a_platform_call_is_recorded_with_its_reason(monkeypatch):
    entries: list[dict] = []
    monkeypatch.setattr(model_call_module, "record_decision", entries.append)
    harness = DRIVERS[DIRECT](monkeypatch, Reply("ok"))
    try:
        with model_call_scope(platform_call("record_without_workspace")):
            await harness.driver.chat(messages=[{"role": "user", "content": "mail a.person@example.org"}],
                                      model=harness.model)
    finally:
        await harness.driver.close()
    (entry,) = entries
    assert entry["platform_scope"] == "record_without_workspace" and entry["workspace_id"] is None


async def test_workspaces_of_one_call_with_different_handling_refuse_it(monkeypatch):
    settings = {"ws-a": {"email": "mask"}, "ws-b": {"email": "refuse"}, "ws-c": {}}

    async def plan(scope, surface):
        return plan_for(settings[scope], surface)

    monkeypatch.setattr(model_call_scope_module, "content_handling_isolated", plan)
    harness = DRIVERS[DIRECT](monkeypatch, Reply("ok"))
    try:
        with model_call_scope(workspace_call(["ws-a", "ws-b"])), pytest.raises(ContentPolicyRefusedError) as refused:
            await harness.driver.chat(messages=[{"role": "user", "content": "hello"}], model=harness.model)
        assert refused.value.content_notice["reason"] == "content_handling_conflict" and harness.sent() == []
        with model_call_scope(workspace_call(["ws-a", "ws-c"])):
            await harness.driver.chat(messages=[{"role": "user", "content": "hello"}], model=harness.model)
    finally:
        await harness.driver.close()
    assert len(harness.sent()) == 1
