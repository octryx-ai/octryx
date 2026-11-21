"""Offline source contract for the one shape in which Pydantic AI may ever appear in ``backend/app``.

``pydantic-ai-slim`` is accepted only behind an Octryx-owned ``HarnessRuntime`` boundary. The dangerous half of
that boundary cannot be enforced by dependency shape: the slim install alone already makes
``pydantic_ai.models.fallback`` and ``pydantic_ai.providers.gateway`` importable, and because ``boto3`` is a base
Octryx dependency, ``pydantic_ai.providers.bedrock`` imports and ``BedrockProvider()`` resolves ambient AWS
credentials with no arguments at all. Nothing in the dependency closure can stop a future module from calling that.

So the boundary is a *source* contract, and this module is its check. It is deliberately in force **before** the
framework exists: today it scans a tree with zero framework references and passes, which is the point — the first
activation slice cannot introduce a forbidden shape without failing a test that already exists. Writing it after the
harness would mean writing it around whatever the harness happened to do.

The five reachability rules are the recorded activation boundary of the gate, restated as source rules:

``framework provider discovery``
    No module may import ``pydantic_ai.providers`` or anything under it, and no name ending in ``Provider`` may be
    imported from the framework at all. Provider selection, credentials and endpoints stay with the Octryx
    model closure.

``fallback models``
    ``pydantic_ai.models`` is importable only for the abstract base classes the Octryx model adapter
    subclasses. Every submodule under it -- ``fallback`` included -- is unreachable, as is ``infer_model``, which
    turns a string into a framework-constructed model.

``gateway constructors``
    ``pydantic_ai.providers.gateway`` and ``GatewayProvider`` are covered by the provider rule and named again in
    ``FORBIDDEN_SYMBOLS`` so a failure says which boundary item broke.

``ambient credentials``
    The boundary package reads no process environment and names none of the framework's credential variables. It
    receives the model closure it is given; it discovers nothing.

``telemetry``
    No Logfire import anywhere under the scanned tree, no OpenTelemetry import and no instrumentation switch inside
    the boundary package. The platform-wide OpenTelemetry decision belongs to its own gate
    (``selected_needs_gate``), so this contract does not
    pre-empt it outside the boundary package. Pydantic AI 2.51 has no ``instrument=`` constructor keyword any more:
    instrumentation is the ``Agent.instrument`` attribute, and an unset attribute inherits the process-wide
    ``Agent.instrument_all()`` default. So every ``Agent`` construction must be assigned to a name and followed in the
    same block by ``<name>.instrument = False``; ``instrument_all`` is unreachable, and ``instrument`` may only ever be
    set to the literal ``False``.

``price data`` (decision D2, TLS-3)
    The framework prices usage from the ``genai-prices`` snapshot bundled in the locked wheel. The boundary never
    imports ``genai_prices`` or ``pydantic_ai.prices``, so it cannot start the background price download whose trust
    anchor is not lock-governed.

Only ``BOUNDARY_PACKAGE`` may import the framework at all. The adapter lives there
(``backend/app/agent/harness``); the contract scans it on every run.

Offline and environment-independent, like every other check in this package: it parses source with ``ast`` and never
imports the scanned code, resolves a dependency or inspects an installed environment. It therefore gives the same
verdict in CI, in a fresh clone and in a worktree with no virtual environment.

Ownership: this module enforces a runtime-architecture boundary from outside the runtime on purpose. It must run
without importing ``backend/app`` (``--noconftest``, no settings, no framework installed), so it stays next to the
adoption gate whose decision it implements. The runtime half -- the import guard and the no-egress proof -- lives in
``backend/tests/test_harness_runtime_parity.py``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .manifest import BACKEND_ROOT

APP_ROOT = BACKEND_ROOT / "app"

# The single package that may import the framework, relative to the scanned root. It does not exist yet.
BOUNDARY_PACKAGE = "agent/harness"

# Top-level import roots that belong to the framework or to its telemetry surface.
FRAMEWORK_ROOTS = frozenset({"pydantic_ai", "pydantic_graph"})
LOGFIRE_ROOTS = frozenset({"logfire", "logfire_api"})
OPENTELEMETRY_ROOTS = frozenset({"opentelemetry"})
# The price-data package whose background updater is the only egress on the second HTTP stack (D2, TLS-3).
PRICE_DATA_ROOTS = frozenset({"genai_prices"})

# A sentinel meaning "any name from this module". The forbidden-symbol rule still applies on top of it, so a module
# opened this way cannot be used to smuggle a forbidden name in.
ANY_NAME: frozenset[str] | None = None

# The framework surface the boundary package may import, and nothing else. Every entry is a value type or an abstract
# base class the Octryx adapter implements; none of them constructs a provider, selects a model or emits
# telemetry. The parity slice extends this map under review, one reasoned name at a time.
ALLOWED_FRAMEWORK_IMPORTS: dict[str, frozenset[str] | None] = {
    # ToolDefinition: the pure value type a toolset lists its tools with. It carries a name, a
    # JSON schema and metadata; it constructs, selects and calls nothing.
    "pydantic_ai": frozenset({"Agent", "RunContext", "ToolDefinition"}),
    # Abstract bases only. The submodules of this package -- `fallback` among them -- are forbidden below.
    "pydantic_ai.models": frozenset({"Model", "ModelRequestParameters", "StreamedResponse"}),
    "pydantic_ai.settings": frozenset({"ModelSettings"}),
    # ToolsetTool: the value wrapper `AbstractToolset.get_tools` must return (toolset, definition,
    # retry budget, argument validator). Listing a tool through it is the abstract base's own contract.
    "pydantic_ai.toolsets": frozenset({"AbstractToolset", "ToolsetTool"}),
    # Pure value types: request/response message parts and token accounting. No provider or model construction.
    "pydantic_ai.messages": ANY_NAME,
    "pydantic_ai.usage": ANY_NAME,
}

# Checked before the allowlist, so no entry above can ever open one of these. `pydantic_ai.models` itself is allowed;
# the trailing dot makes this rule its submodules only.
FORBIDDEN_MODULE_PREFIXES: dict[str, str] = {
    "pydantic_ai.providers": "framework provider discovery",
    "pydantic_ai.models.": "fallback and framework-constructed models",
    "pydantic_ai.mcp": "framework-owned MCP client",
    "pydantic_ai.prices": "price-data egress (D2, TLS-3)",
}

# Named individually so a failure reports the boundary item rather than only the module.
FORBIDDEN_SYMBOLS: dict[str, str] = {
    "FallbackModel": "fallback models",
    "infer_model": "framework model construction from a string",
    "GatewayProvider": "gateway constructors",
    "gateway_provider": "gateway constructors",
    "InstrumentationSettings": "telemetry",
    "instrument_all": "telemetry",
}

# Confirmed by the adoption gate probe as credential variables the framework reads itself.
FRAMEWORK_CREDENTIAL_ENV_NAMES = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "AWS_BEARER_TOKEN_BEDROCK",
        "GITHUB_COPILOT_API_TOKEN",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "OPENROUTER_API_KEY",
        "PYDANTIC_AI_GATEWAY_API_KEY",
    }
)

# Attribute names that read the process environment, however `os` was imported.
AMBIENT_ENVIRONMENT_ACCESSORS = frozenset({"environ", "getenv"})


@dataclass(frozen=True, slots=True)
class Violation:
    """One breach of the boundary contract: which rule, where, and what to do about it."""

    rule: str
    location: str
    detail: str


def _display_path(path: Path, root: Path) -> str:
    """Render a scanned file backend-relative, falling back to root-relative for a synthetic tree under test."""
    for anchor in (BACKEND_ROOT, root.parent):
        try:
            return str(path.relative_to(anchor))
        except ValueError:
            continue
    return str(path)


def _root_of(module: str) -> str:
    return module.split(".")[0]


def forbidden_prefix(module: str) -> tuple[str, str] | None:
    """Return the forbidden prefix covering ``module``, if any.

    A prefix that ends with a dot covers the submodules of a package but not the package itself: ``pydantic_ai.models``
    is allowed for its abstract bases while everything under it, ``fallback`` included, is not.
    """
    for prefix, boundary_item in FORBIDDEN_MODULE_PREFIXES.items():
        if prefix.endswith("."):
            if module.startswith(prefix):
                return prefix, boundary_item
        elif module == prefix or module.startswith(f"{prefix}."):
            return prefix, boundary_item
    return None


def _check_framework_import_from(
    node: ast.ImportFrom, module: str, location: str, in_boundary: bool
) -> Iterator[Violation]:
    """Apply the framework rules to one ``from <module> import <names>`` statement."""
    if not in_boundary:
        yield Violation(
            rule="framework-import-site",
            location=location,
            detail=(
                f"'{module}' is imported outside the boundary package; only backend/app/{BOUNDARY_PACKAGE}/ may "
                f"reach Pydantic AI"
            ),
        )
        return

    forbidden = forbidden_prefix(module)
    if forbidden is not None:
        prefix, boundary_item = forbidden
        yield Violation(
            rule="framework-module",
            location=location,
            detail=f"'{module}' is under '{prefix}', which the activation boundary makes unreachable ({boundary_item})",
        )
        return

    if module not in ALLOWED_FRAMEWORK_IMPORTS:
        yield Violation(
            rule="framework-module",
            location=location,
            detail=(
                f"'{module}' is not in ALLOWED_FRAMEWORK_IMPORTS; add it there with a reason under review, or keep "
                f"the adapter off it"
            ),
        )
        return

    allowed = ALLOWED_FRAMEWORK_IMPORTS[module]
    for alias in node.names:
        if _symbol_detail(alias.name) is not None:
            continue  # reported once, by the rule that names the boundary item rather than the module
        if isinstance(allowed, frozenset) and alias.name not in allowed:
            yield Violation(
                rule="framework-symbol",
                location=location,
                detail=f"'{alias.name}' is not an allowed name of '{module}' (allowed: {', '.join(sorted(allowed))})",
            )


def _symbol_detail(name: str) -> str | None:
    """Return why ``name`` is unreachable through the boundary, or ``None`` when the name is not itself forbidden."""
    boundary_item = FORBIDDEN_SYMBOLS.get(name)
    if boundary_item is not None:
        return f"'{name}' is unreachable through the boundary ({boundary_item})"
    if name.endswith("Provider"):
        return f"'{name}' is a framework provider class; provider selection stays in the model closure"
    return None


def _check_symbol_names(names: list[str], location: str) -> Iterator[Violation]:
    for name in names:
        detail = _symbol_detail(name)
        if detail is not None:
            yield Violation(rule="framework-symbol", location=location, detail=detail)


def _price_data_violation(module: str, location: str) -> Violation:
    return Violation(
        rule="price-data-import",
        location=location,
        detail=f"'{module}' is unreachable inside the boundary package; price data stays the locked local snapshot",
    )


def _check_imports(tree: ast.AST, location_of, in_boundary: bool) -> Iterator[Violation]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _root_of(alias.name)
                if root in FRAMEWORK_ROOTS:
                    yield Violation(
                        rule="framework-bare-import",
                        location=location_of(node),
                        detail=(
                            f"'import {alias.name}' gives attribute reach to every framework submodule; import the "
                            f"exact allowed names with 'from ... import ...' instead"
                        ),
                    )
                elif root in LOGFIRE_ROOTS:
                    yield Violation(
                        rule="telemetry-import",
                        location=location_of(node),
                        detail=f"'{alias.name}' is framework telemetry; the boundary initialises no Logfire",
                    )
                elif root in OPENTELEMETRY_ROOTS and in_boundary:
                    yield Violation(
                        rule="telemetry-import",
                        location=location_of(node),
                        detail=f"'{alias.name}' is unreachable inside the boundary package; it exports no telemetry",
                    )
                elif root in PRICE_DATA_ROOTS and in_boundary:
                    yield _price_data_violation(alias.name, location_of(node))
                elif root == "importlib" and in_boundary:
                    yield Violation(
                        rule="dynamic-import",
                        location=location_of(node),
                        detail=(
                            "the boundary package may not use importlib; framework imports must remain statically "
                            "reviewable"
                        ),
                    )
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            root = _root_of(node.module)
            location = location_of(node)
            if root in FRAMEWORK_ROOTS:
                yield from _check_framework_import_from(node, node.module, location, in_boundary)
                yield from _check_symbol_names([alias.name for alias in node.names], location)
            elif root in LOGFIRE_ROOTS:
                yield Violation(
                    rule="telemetry-import",
                    location=location,
                    detail=f"'{node.module}' is framework telemetry; the boundary initialises no Logfire",
                )
            elif root in OPENTELEMETRY_ROOTS and in_boundary:
                yield Violation(
                    rule="telemetry-import",
                    location=location,
                    detail=f"'{node.module}' is unreachable inside the boundary package; it exports no telemetry",
                )
            elif root in PRICE_DATA_ROOTS and in_boundary:
                yield _price_data_violation(node.module, location)
            elif root == "importlib" and in_boundary:
                yield Violation(
                    rule="dynamic-import",
                    location=location,
                    detail=(
                        "the boundary package may not use importlib; framework imports must remain statically "
                        "reviewable"
                    ),
                )


def _attribute_chain(node: ast.Attribute) -> str | None:
    """Render ``a.b.c`` as a dotted string, or return ``None`` for a chain that is not rooted in a plain name."""
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _check_boundary_body(tree: ast.AST, location_of) -> Iterator[Violation]:
    """Rules that apply only inside the boundary package: no ambient credentials, no instrumentation switch."""
    os_aliases = {"os"}
    ambient_accessor_aliases = set(AMBIENT_ENVIRONMENT_ACCESSORS)
    agent_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "os":
                    os_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            for alias in node.names:
                if alias.name in AMBIENT_ENVIRONMENT_ACCESSORS:
                    ambient_accessor_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "pydantic_ai":
            for alias in node.names:
                if alias.name == "Agent":
                    agent_aliases.add(alias.asname or alias.name)

    # `a.b.c` contains `a.b`, which contains `a`. Only the outermost attribute of a chain is reported, so one
    # expression yields one violation naming the whole path rather than three naming its prefixes.
    inner = {id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            chain = _attribute_chain(node)
            if chain is None or id(node) in inner:
                continue
            parts = chain.split(".")
            if parts[0] in FRAMEWORK_ROOTS:
                yield Violation(
                    rule="framework-attribute",
                    location=location_of(node),
                    detail=f"'{chain}' reaches the framework by attribute; only the allowed imported names may be used",
                )
            elif parts[0] in os_aliases and parts[1:2] and parts[1] in AMBIENT_ENVIRONMENT_ACCESSORS:
                yield Violation(
                    rule="ambient-environment",
                    location=location_of(node),
                    detail=(
                        f"'{chain}' reads the process environment; the boundary receives the model closure and "
                        f"discovers no credential"
                    ),
                )
        elif isinstance(node, ast.Name) and node.id in ambient_accessor_aliases:
            yield Violation(
                rule="ambient-environment",
                location=location_of(node),
                detail=(
                    f"'{node.id}' reads the process environment; the boundary receives the model closure and "
                    f"discovers no credential"
                ),
            )
        elif isinstance(node, ast.Constant) and node.value in FRAMEWORK_CREDENTIAL_ENV_NAMES:
            yield Violation(
                rule="ambient-credential-name",
                location=location_of(node),
                detail=f"'{node.value}' is a credential variable the framework reads itself; the boundary names none",
            )
        elif isinstance(node, ast.keyword) and node.arg == "instrument":
            if not (isinstance(node.value, ast.Constant) and node.value.value is False):
                yield Violation(
                    rule="telemetry-instrumentation",
                    location=location_of(node.value),
                    detail="'instrument=' may only be the literal False; the boundary emits no framework telemetry",
                )
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "__import__":
            yield Violation(
                rule="dynamic-import",
                location=location_of(node),
                detail=(
                    "the boundary package may not use __import__; framework imports must remain statically reviewable"
                ),
            )
    yield from _check_agent_instrumentation(tree, agent_aliases, location_of)


def _is_instrument_off(statement: ast.stmt, target: str) -> bool:
    """``<target>.instrument = False``, and nothing looser."""
    return (
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Attribute)
        and statement.targets[0].attr == "instrument"
        and ast.unparse(statement.targets[0].value) == target
        and isinstance(statement.value, ast.Constant)
        and statement.value.value is False
    )


def _statement_blocks(tree: ast.AST) -> Iterator[list[ast.stmt]]:
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                yield block


def _check_agent_instrumentation(tree: ast.AST, agent_aliases: set[str], location_of) -> Iterator[Violation]:
    """Every Agent is assigned and switched off in the same block; ``instrument`` is only ever set to ``False``."""

    def is_agent_call(node: ast.AST) -> bool:
        return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in agent_aliases

    switched_off: set[int] = set()
    for block in _statement_blocks(tree):
        for index, statement in enumerate(block):
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and is_agent_call(statement.value):
                target = ast.unparse(statement.targets[0])
                if any(_is_instrument_off(later, target) for later in block[index + 1 :]):
                    switched_off.add(id(statement.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "instrument_all":
            yield Violation(
                rule="telemetry-instrumentation",
                location=location_of(node),
                detail="'instrument_all' switches framework telemetry on process-wide; the boundary never reaches it",
            )
        elif is_agent_call(node) and id(node) not in switched_off:
            yield Violation(
                rule="telemetry-instrumentation",
                location=location_of(node),
                detail=(
                    "every Agent construction must be assigned and followed in the same block by "
                    "'<name>.instrument = False'"
                ),
            )
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Attribute) and target.attr == "instrument" for target in node.targets
        ):
            if not (isinstance(node.value, ast.Constant) and node.value.value is False):
                yield Violation(
                    rule="telemetry-instrumentation",
                    location=location_of(node),
                    detail="'instrument' may only be set to the literal False; the boundary emits no telemetry",
                )


def scan_boundary(root: Path = APP_ROOT) -> list[Violation]:
    """Return every breach of the Pydantic AI boundary contract in the source tree under ``root``."""
    violations: list[Violation] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        in_boundary = relative == f"{BOUNDARY_PACKAGE}.py" or relative.startswith(f"{BOUNDARY_PACKAGE}/")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        display = _display_path(path, root)

        def location_of(node: ast.AST, _display: str = display) -> str:
            return f"{_display}:{getattr(node, 'lineno', 0)}"

        violations.extend(_check_imports(tree, location_of, in_boundary))
        if in_boundary:
            violations.extend(_check_boundary_body(tree, location_of))
    return violations


def format_violations(violations: list[Violation]) -> str:
    """Render violations as an actionable failure message, grouped by rule in a stable order."""
    lines = []
    for violation in sorted(violations, key=lambda item: (item.rule, item.location)):
        lines.append(f"  [{violation.rule}] {violation.location}: {violation.detail}")
    return "\n".join(lines)
