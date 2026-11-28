"""Every request to a model goes through an enforcement entry point, except two named ones that send only their fixed
probe text: the bundled route check and the alias qualification."""

from __future__ import annotations

import ast
from pathlib import Path

from app.services.model_gateway.litellm.qualification_codes import QUALIFICATION_MESSAGES

APP = Path(__file__).resolve().parents[2] / "app"
#: (module, enclosing function) → why the request needs no enforcement.
EXCEPTIONS = {
    ("services/model_gateway/bundled_routes.py", "test_route"):
        "the route check sends a fixed probe with the platform's own virtual key",
    ("services/model_gateway/litellm/qualification.py", "run_alias_qualification"):
        "the alias qualification sends a fixed probe through the final-bytes check",
}
#: The provider driver: BaseLLMProvider wraps its chat with content_security.model_call.enforced_chat.
ENFORCED = {("agent/providers/litellm_gateway.py", "LiteLLMGatewayClient.chat")}
#: A request to a model: the LiteLLM client's call, or a post to a chat completions URL.
MODEL_PATH = "/v1/chat/completions"


def _sites() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module = path.relative_to(APP).as_posix()
        for scope, node in _calls(tree):
            if _model_request(node):
                found.add((module, scope))
    return found


def _calls(tree: ast.Module, prefix: str = ""):
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            yield from _calls(node, f"{prefix}{node.name}.")
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call):
                    yield f"{prefix}{node.name}", inner


def _model_request(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr == "chat_completion":
        return True
    return (isinstance(func, ast.Attribute) and func.attr == "post" and bool(call.args)
            and MODEL_PATH in ast.unparse(call.args[0]))


def test_every_model_request_is_enforced_or_a_named_exception():
    assert _sites() == ENFORCED | set(EXCEPTIONS)


def test_the_route_check_sends_only_its_fixed_probe():
    tree = ast.parse((APP / "services/model_gateway/bundled_routes.py").read_text(encoding="utf-8"))
    (function,) = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "test_route"]
    (post,) = [node for node in ast.walk(function) if isinstance(node, ast.Call) and _model_request(node)]
    (body,) = [keyword.value for keyword in post.keywords if keyword.arg == "json"]
    messages = next(value for key, value in zip(body.keys, body.values, strict=True)
                    if isinstance(key, ast.Constant) and key.value == "messages")
    assert ast.literal_eval(messages) == [{"role": "user", "content": "Reply with OK."}]


def test_the_alias_qualification_sends_only_its_fixed_probe():
    assert QUALIFICATION_MESSAGES == ({"role": "user", "content": "ping"},)
    tree = ast.parse((APP / "services/model_gateway/litellm/qualification.py").read_text(encoding="utf-8"))
    (call,) = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and _model_request(node)]
    (messages,) = [keyword.value for keyword in call.keywords if keyword.arg == "messages"]
    assert "QUALIFICATION_MESSAGES" in ast.unparse(messages) and not any(
        isinstance(node, ast.Name) and node.id not in {"QUALIFICATION_MESSAGES", "dict", "message"}
        for node in ast.walk(messages))
