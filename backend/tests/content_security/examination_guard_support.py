"""The resolver behind the examination guard (``test_examination_guard``): every scanner use and every consumer."""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field

SCANNER = "app.services.content_detection.scanner"
CONTRACT = "app.services.content_detection.examination"
DETECTION_PACKAGE = "app.services.content_detection"
SCANNER_FUNCTIONS = frozenset({"scan", "scan_text", "merge_reports", "_find"})
FINDERS = frozenset({"find_builtin", "find_platform", "find_prompt_injection", "find_credential_assignments",
                     "find_internal_ips"})
ALLOWED_SCANNER_USERS = frozenset({SCANNER, CONTRACT})
# ``knowledge.sources.sync.runner`` reads ``unfinished`` of its own paging report (a sync cursor), not a scan.
ALLOWED_UNFINISHED_READERS = frozenset({SCANNER, CONTRACT, "app.services.knowledge.sources.sync.runner"})

#: Consumed interfaces: module → the names whose use makes a module a consumer (``None``: every name).
INTERFACES: Mapping[str, frozenset[str] | None] = {
    CONTRACT: None,
    "app.services.content_routing.decision": frozenset({"scan_for", "decide_model_content", "decide_tool_result"}),
    "app.services.content_routing.client_tool_results": frozenset({"launcher_tool_result",
                                                                   "client_tool_result_denial"}),
    "octryx_claude.content_hooks": frozenset({"content_output"}),
    # Indirect boundaries: the tool-result decision its adapters forward, the gateway plan its routes
    # dispatch (the planners and their route-facing callers), and the provider boundary every driver class is
    # wrapped with.
    "app.services.content_routing.tool_results": frozenset({"check_tool_result"}),
    "app.services.content_security.enforcement_inbound": frozenset({"enforce_inbound"}),
    "app.services.model_gateway.inbound.service": frozenset({"content_plan", "governed_plan"}),
    "app.services.model_gateway.inbound.seat_content": frozenset({"seat_content_plan"}),
    "app.services.content_security.model_call": frozenset({"enforced_chat"}),
    # Result-consuming edges: the gateway's scan of the forwarded body and the decisions that consume it (fixed
    # rules, the Workspace's content handling, the Cedar and tool-result refusals).
    "app.services.content_security.format_request_body": frozenset({"examine_request_body"}),
    "app.services.content_routing.gateway": frozenset({"fixed_refusal", "handling_refusal", "content_refusal",
                                                       "tool_result_refusal"}),
    "app.services.content_detection.request_examination": frozenset({"RequestExaminer"}),
}
#: Methods of an examination result that hand its findings on: result type → (its producers, method names). A module
#: holds the result when it uses a producer or defines the type; there each call of such a method is an edge.
RESULT_METHODS: Mapping[str, tuple[frozenset[str], frozenset[str]]] = {
    "app.services.content_security.format_request_body.GatewayScan": (
        frozenset({"app.services.content_security.format_request_body.examine_request_body"}),
        frozenset({"secret_kinds"})),
}
#: The disposition fields of ``client_tool_results.launcher_tool_result`` only a launcher consumer reads.
LAUNCHER_FIELDS = frozenset({"updated_output"})
LAUNCHER_PACKAGE = "octryx_claude"


@dataclass
class Module:
    name: str
    tree: ast.Module
    package: bool
    bindings: dict[str, str] = field(default_factory=dict)
    nodes: list[ast.AST] = field(default_factory=list)
    assignments: list[tuple[str, ast.AST]] = field(default_factory=list)


def _absolute(module: Module, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    package = module.name.split(".") if module.package else module.name.split(".")[:-1]
    base = package[:len(package) - node.level + 1]
    return ".".join([*base, node.module] if node.module else base)


def _raw(expr: ast.AST, bindings: Mapping[str, str]) -> str:
    if isinstance(expr, ast.Name):
        return bindings.get(expr.id, "")
    if isinstance(expr, ast.Attribute):
        base = _raw(expr.value, bindings)
        return f"{base}.{expr.attr}" if base else ""
    if (isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "getattr"
            and len(expr.args) >= 2 and isinstance(expr.args[1], ast.Constant) and isinstance(expr.args[1].value, str)):
        base = _raw(expr.args[0], bindings)
        return f"{base}.{expr.args[1].value}" if base else ""
    return ""


class Resolver:
    def __init__(self, sources: Mapping[str, tuple[str, bool]]) -> None:
        self.modules = {name: Module(name, ast.parse(text), package) for name, (text, package) in sources.items()}
        self._canonical: dict[str, str] = {}
        for module in self.modules.values():
            module.nodes = list(ast.walk(module.tree))
            self._bind_imports(module)
        for _round in range(4):  # assignments of resolvable names, also across modules
            for module in self.modules.values():
                self._bind_assignments(module)
            self._canonical.clear()

    def _bind_imports(self, module: Module) -> None:
        for node in module.nodes:
            if isinstance(node, ast.Assign | ast.AnnAssign | ast.NamedExpr) and node.value is not None:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                module.assignments += [(target.id, node.value) for target in targets if isinstance(target, ast.Name)]
            elif isinstance(node, ast.ImportFrom):
                source = _absolute(module, node)
                for name in node.names:
                    if name.name != "*":
                        module.bindings[name.asname or name.name] = f"{source}.{name.name}"
            elif isinstance(node, ast.Import):
                for name in node.names:
                    if name.asname:
                        module.bindings[name.asname] = name.name
                    else:
                        head = name.name.split(".")[0]
                        module.bindings[head] = head

    def _bind_assignments(self, module: Module) -> None:
        for name, value in module.assignments:
            resolved = self.canonical(_raw(value, module.bindings))
            if resolved:
                module.bindings[name] = resolved

    def canonical(self, dotted: str) -> str:
        if dotted not in self._canonical:
            self._canonical[dotted] = self._follow(dotted) if dotted else ""
        return self._canonical[dotted]

    def _follow(self, dotted: str) -> str:
        for _hop in range(16):
            parts = dotted.split(".")
            for cut in range(len(parts) - 1, 0, -1):
                owner = self.modules.get(".".join(parts[:cut]))
                if owner is not None and parts[cut] in owner.bindings:
                    target = owner.bindings[parts[cut]]
                    if target != ".".join(parts[:cut + 1]):
                        dotted = ".".join([target, *parts[cut + 1:]])
                        break
            else:
                return dotted
        return dotted

    def resolve(self, module: Module, expr: ast.AST) -> str:
        return self.canonical(_raw(expr, module.bindings))


def _protected(target: str) -> str:
    module, _, name = target.rpartition(".")
    if module == SCANNER and name in SCANNER_FUNCTIONS:
        return f"scanner function {name}"
    if module.startswith(DETECTION_PACKAGE) and name in FINDERS:
        return f"detector finder {name}"
    return ""


def _allowed(module: str, what: str) -> bool:
    if what.startswith("detector finder"):
        return module.startswith(DETECTION_PACKAGE)
    return module in ALLOWED_SCANNER_USERS


def _dynamic_scanner_import(node: ast.Call) -> bool:
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
    return name in {"import_module", "__import__"} and any(
        isinstance(arg, ast.Constant) and isinstance(arg.value, str) and "content_detection" in arg.value
        for arg in node.args)


def _interface_name(target: str) -> str:
    for owner, names in INTERFACES.items():
        if target == owner:
            return owner if names is None else ""
        if target.startswith(f"{owner}."):
            name = target[len(owner) + 1:].split(".")[0]
            return f"{owner}.{name}" if names is None or name in names else ""
    return ""


def _interface(target: str) -> bool:
    return bool(_interface_name(target))


def _scopes(tree: ast.Module) -> tuple[dict[int, str], set[int]]:
    scope: dict[int, str] = {}
    annotations: set[int] = set()

    def mark(node: ast.AST | None) -> None:
        if node is not None:
            annotations.update(id(item) for item in ast.walk(node))

    def visit(node: ast.AST, name: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = name
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                inner = child.name if name == "<module>" else f"{name}.{child.name}"
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                mark(child.returns)
                for argument in (*child.args.posonlyargs, *child.args.args, *child.args.kwonlyargs,
                                 child.args.vararg, child.args.kwarg):
                    mark(argument.annotation if argument else None)
            elif isinstance(child, ast.AnnAssign):
                mark(child.annotation)
            scope[id(child)] = inner
            visit(child, inner)

    visit(tree, "<module>")
    return scope, annotations


def edge(module: str, scope: str, interface: str, site: int = 1) -> str:
    key = f"{module}:{scope} -> {interface}"
    return key if site == 1 else f"{key} #{site}"


def _result_methods(resolver: Resolver, module: Module) -> list[tuple[str, str]]:
    found = []
    for result, (producers, names) in RESULT_METHODS.items():
        defines = result.rpartition(".")[0] == module.name
        uses = any(resolver.resolve(module, node) in producers for node in module.nodes
                   if isinstance(node, ast.Name | ast.Attribute) and isinstance(node.ctx, ast.Load))
        if defines or uses:
            found += [(f"{result}.{name}", name) for name in sorted(names)]
    return found


def _edges(resolver: Resolver, module: Module) -> list[str]:
    scope, annotations = _scopes(module.tree)
    found: dict[int, str] = {}
    for node in module.nodes:
        if isinstance(node, ast.Name | ast.Attribute) and isinstance(node.ctx, ast.Load) \
                and id(node) not in annotations:
            name = _interface_name(resolver.resolve(module, node))
            if name and not name.rpartition(".")[2].isupper():
                found[id(node)] = name
    for interface, name in _result_methods(resolver, module):
        for node in module.nodes:
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == name:
                found[id(node.func)] = interface
    inner = {id(node.value) for node in module.nodes
             if isinstance(node, ast.Attribute) and id(node) in found and found.get(id(node.value)) == found[id(node)]}
    seen: Counter[str] = Counter()
    keys = []
    for node in module.nodes:
        if id(node) in found and id(node) not in inner:
            base = edge(module.name, scope.get(id(node), "<module>"), found[id(node)])
            seen[base] += 1
            keys.append(edge(module.name, scope.get(id(node), "<module>"), found[id(node)], seen[base]))
    return keys


def sites(sources: Mapping[str, tuple[str, bool]]) -> dict[str, object]:
    resolver = Resolver(sources)
    violations: dict[str, list[str]] = {}
    consumers: set[str] = set()
    edges: list[str] = []
    for module in resolver.modules.values():
        if module.name != CONTRACT:
            edges += _edges(resolver, module)
        found: list[str] = []
        for node in module.nodes:
            if isinstance(node, ast.ImportFrom):
                source = _absolute(module, node)
                for name in node.names:
                    target = resolver.canonical(f"{source}.{name.name}")
                    what = _protected(target)
                    if what and not _allowed(module.name, what):
                        found.append(f"imports {what} at line {node.lineno}")
                    consumers.update({module.name} if _interface(target) else set())
            elif isinstance(node, ast.Name | ast.Attribute) and isinstance(node.ctx, ast.Load):
                target = resolver.resolve(module, node)
                what = _protected(target)
                if what and not _allowed(module.name, what):
                    found.append(f"uses {what} at line {node.lineno}")
                consumers.update({module.name} if target and _interface(target) else set())
                if isinstance(node, ast.Attribute) and node.attr == "unfinished" \
                        and module.name not in ALLOWED_UNFINISHED_READERS:
                    found.append(f"reads .unfinished at line {node.lineno}")
            elif isinstance(node, ast.Call):
                target = resolver.resolve(module, node.func)
                if target == f"{SCANNER}.ScanReport" and module.name not in ALLOWED_SCANNER_USERS:
                    found.append(f"constructs ScanReport at line {node.lineno}")
                via_getattr = resolver.resolve(module, node)
                what = _protected(via_getattr)
                if what and not _allowed(module.name, what):
                    found.append(f"uses {what} through getattr at line {node.lineno}")
                if isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) >= 2 \
                        and isinstance(node.args[1], ast.Constant) and node.args[1].value == "unfinished" \
                        and module.name not in ALLOWED_UNFINISHED_READERS:
                    found.append(f"reads .unfinished through getattr at line {node.lineno}")
                if _dynamic_scanner_import(node) and module.name not in ALLOWED_SCANNER_USERS:
                    found.append(f"imports the scanner dynamically at line {node.lineno}")
            elif isinstance(node, ast.Constant) and node.value in LAUNCHER_FIELDS \
                    and module.name.startswith(f"{LAUNCHER_PACKAGE}."):
                consumers.add(module.name)
        if found:
            violations[module.name] = found
    consumers.discard(CONTRACT)
    return {"violations": violations, "consumers": sorted(consumers), "edges": sorted(edges)}
