"""Offline check that every third-party distribution ``backend/app`` imports is declared by the project.

Why: ``app/services/office_identity/layout_authoring.py`` imported ``lxml`` at module level while neither
``backend/pyproject.toml`` nor ``backend/uv.lock`` declared it, so every install path that followed the declared
contract produced an API image that exited at import with ``ModuleNotFoundError``. Two local virtual environments hid
it, because the packages had been installed by hand. This module is the guard that makes that class of defect a test
failure instead of a build failure.

Offline and environment-independent: it parses source with ``ast`` and reads ``backend/pyproject.toml`` with
``tomllib``. It never imports the scanned code, never resolves a dependency and never inspects the installed
environment, so it gives the same verdict in CI, in a fresh clone and in a worktree without a virtual environment.
Deriving the verdict from installed metadata would be exactly the mistake that let that defect through.

How an import is classified, from the statement chain between the module body and the import statement:

``typing_only``
    Inside an ``if TYPE_CHECKING:`` block. Never executed at runtime, so it is not a dependency at all and is ignored.

``required``
    Executed when the module is imported, with no ``ImportError`` handling anywhere in its chain. A missing
    distribution here is a crash before the first request — that failure mode. It must be declared in
    ``[project].dependencies``, and no allowlist entry can excuse it: an extra would not be installed and a guard does
    not exist.

``guarded``
    Executed at import time, but in the ``try`` *body* of a ``try`` whose handler catches ``ImportError``/
    ``ModuleNotFoundError``/``Exception``. The module still imports when the distribution is absent. Only the try body
    counts: a ``try`` protects nothing that runs in its own ``except``, ``else`` or ``finally`` branch, because by then
    the handler is either already running or already past.

``deferred``
    Inside a function, method or lambda body, so it runs only if that code path runs. A **class body is not deferred**:
    it executes while the module is being imported, exactly like a module-level statement, so a class-body import is
    ``required`` unless a ``try`` guards it.

``guarded`` and ``deferred`` imports must be declared in the project dependencies or one of its extras, or carry an
explicit entry in ``OPTIONAL_IMPORT_ALLOWLIST``. "It happens to be installed" is not a reason: ``pyyaml`` reached the
locked closure only through ``uvicorn[standard]`` while three service modules imported it at module level, which is
the same latent defect one dependency-tree change away.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .manifest import BACKEND_ROOT, PYPROJECT_PATH, canonical_name

APP_ROOT = BACKEND_ROOT / "app"

# Top-level packages that belong to this repository rather than to a distribution.
FIRST_PARTY = frozenset({"app"})

# Import names whose top-level module differs from the distribution that provides it. Every other name maps by the
# PEP 503 rule alone (``pydantic_settings`` -> ``pydantic-settings``). An unlisted name therefore maps to itself, which
# fails closed: a new undeclared import is reported under its import name rather than silently resolved.
IMPORT_NAME_TO_DISTRIBUTION = {
    "PIL": "pillow",
    "docx": "python-docx",
    "google": "google-cloud-storage",
    "jwt": "pyjwt",
    "pptx": "python-pptx",
    # The harness boundary imports the framework from the slim distribution, the one the adoption gate approved.
    "pydantic_ai": "pydantic-ai-slim",
    "pyannote": "pyannote-audio",
    "re2": "google-re2",
    "yaml": "pyyaml",
}

# Distributions that only an optional, install-gated code path imports and that the product deliberately does not
# declare. Every entry states why the product still works without it; "it is not installed in CI" is not a reason, and
# a ``required`` import can never be listed here.
#
# These are the honest remainder of this boundary rule rather than a clean state: each one is a capability that
# degrades when the distribution is absent, and each would become a declared base dependency or a governed extra only
# together with an explicit optional-feature contract, which is out of scope here.
OPTIONAL_IMPORT_ALLOWLIST = {
    "botocore": (
        "implementation package of the declared boto3, which pins it to a narrow range; boto3 cannot resolve without "
        "it, so a second declared floor would add resolver-conflict risk and no availability"
    ),
    "google-cloud-storage": (
        "optional Google Cloud Storage backend of the artifact store; the store selects a backend at call time and the "
        "S3/filesystem backends carry the product default"
    ),
    "html2text": "optional HTML-to-markdown conversion in the markup tool; the tool falls back without it",
    "numpy": (
        "speaker diarization only; imported under a module-level try/except ImportError that leaves the module usable, "
        "and it reaches the lock transitively through the knowledge extra's fastembed"
    ),
    "torch": (
        "speaker diarization only; imported under the same module-level try/except ImportError. A declared base "
        "dependency would add a multi-hundred-megabyte ML stack to every API and worker image"
    ),
    "pyannote-audio": "speaker diarization models, loaded only when diarization is configured and numpy/torch resolved",
    "sentence-transformers": (
        "alternative in-process embedding model of the knowledge embedding driver; the driver reports "
        "needs_configuration when the backing library is absent"
    ),
}

_IMPORT_ERROR_NAMES = frozenset({"ImportError", "ModuleNotFoundError", "Exception", "BaseException"})

# ``try``/``except`` and ``try``/``except*``. ``except* ImportError`` also catches a plain ``ImportError``: PEP 654
# wraps a non-group exception before matching, so it degrades as gracefully as a plain handler.
_TRY_NODES = (ast.Try, ast.TryStar)

REQUIRED = "required"
GUARDED = "guarded"
DEFERRED = "deferred"
TYPING_ONLY = "typing_only"


@dataclass(frozen=True, slots=True)
class ImportSite:
    """One import of one top-level module, with where it is and whether it runs at import time."""

    module: str
    distribution: str
    kind: str
    location: str


@dataclass(frozen=True, slots=True)
class DeclaredContract:
    """The distribution names ``backend/pyproject.toml`` declares, split by how an install path reaches them."""

    base: frozenset[str]
    extras: frozenset[str]


def distribution_for(module: str) -> str:
    """Return the canonical distribution name that provides top-level module ``module``."""
    return canonical_name(IMPORT_NAME_TO_DISTRIBUTION.get(module, module))


def read_declared_contract(pyproject_path: Path = PYPROJECT_PATH) -> DeclaredContract:
    """Read the declared distributions, keeping base dependencies distinct from extras.

    Dependency groups are deliberately excluded: they are development tooling and reach no runtime install path.
    """
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8")).get("project", {})
    base = {_requirement_name(item) for item in project.get("dependencies", [])}
    extras: set[str] = set()
    for requirements in (project.get("optional-dependencies") or {}).values():
        extras.update(_requirement_name(item) for item in requirements)
    return DeclaredContract(frozenset(base - {""}), frozenset(extras - {""}))


def _requirement_name(requirement: str) -> str:
    """Return the canonical distribution name of a PEP 508 requirement string."""
    head = requirement.split(";")[0].strip()
    for separator in ("[", "=", ">", "<", "!", "~", " ", "@"):
        head = head.split(separator)[0]
    return canonical_name(head.strip()) if head.strip() else ""


def _classify(node: ast.AST, chain: tuple[ast.AST, ...]) -> str:
    """Classify an import from the import statement and the statement nodes enclosing it, outermost first."""
    descendants = (*chain, node)
    if any(_is_type_checking_guard(ancestor, descendants) for ancestor in chain):
        return TYPING_ONLY
    # A class body is deliberately absent here: it runs while the module is imported, so an import in one is as
    # eager as a module-level import. Only a function, method or lambda body actually defers execution.
    if any(isinstance(ancestor, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) for ancestor in chain):
        return DEFERRED
    if any(_is_import_error_guard(ancestor, descendants) for ancestor in chain):
        return GUARDED
    return REQUIRED


def _in_body(node: ast.stmt | ast.AST, body: list[ast.stmt], descendants: tuple[ast.AST, ...]) -> bool:
    """Whether any node of ``descendants`` is inside the statement list ``body``."""
    body_ids = {id(child) for statement in body for child in ast.walk(statement)}
    return any(id(other) in body_ids for other in descendants)


def _is_type_checking_guard(node: ast.AST, descendants: tuple[ast.AST, ...]) -> bool:
    """Whether ``node`` is an ``if TYPE_CHECKING:`` test whose *body* (not its ``else``) contains the import."""
    if not isinstance(node, ast.If):
        return False
    test = node.test
    name = test.attr if isinstance(test, ast.Attribute) else test.id if isinstance(test, ast.Name) else None
    if name != "TYPE_CHECKING":
        return False
    return _in_body(node, node.body, descendants)


def _is_import_error_guard(node: ast.AST, descendants: tuple[ast.AST, ...]) -> bool:
    """Whether ``node`` is a ``try`` that catches a missing import *and* runs the import in its own ``try`` body.

    The branch matters. An import in an ``except`` handler runs because the guarded attempt already failed, an import
    in ``else`` runs outside the handler's reach, and an import in ``finally`` runs after the handler is done — in all
    three the ``ImportError`` propagates, so the module fails to import exactly as if there were no ``try`` at all.
    """
    if not isinstance(node, _TRY_NODES) or not _handles_import_error(node):
        return False
    return _in_body(node, node.body, descendants)


def _handles_import_error(node: ast.Try | ast.TryStar) -> bool:
    """Whether a ``try`` statement has a handler that catches a missing import."""
    for handler in node.handlers:
        if handler.type is None:
            return True
        candidates = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
        for candidate in candidates:
            caught = candidate.attr if isinstance(candidate, ast.Attribute) else getattr(candidate, "id", None)
            if caught in _IMPORT_ERROR_NAMES:
                return True
    return False


def _walk(node: ast.AST, chain: tuple[ast.AST, ...]) -> Iterator[tuple[ast.AST, tuple[ast.AST, ...]]]:
    """Yield every node with the tuple of statement nodes enclosing it, outermost first."""
    yield node, chain
    for child in ast.iter_child_nodes(node):
        yield from _walk(child, (*chain, node))


def _display_path(path: Path, root: Path) -> str:
    """Render a scanned file backend-relative, falling back to root-relative for a synthetic tree under test."""
    for anchor in (BACKEND_ROOT, root.parent):
        try:
            return str(path.relative_to(anchor))
        except ValueError:
            continue
    return str(path)


def scan_imports(root: Path = APP_ROOT) -> list[ImportSite]:
    """Return every third-party import site under ``root``, excluding the standard library and first-party packages."""
    standard_library = set(sys.stdlib_module_names)
    sites: list[ImportSite] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node, chain in _walk(tree, ()):
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module.split(".")[0]] if node.level == 0 and node.module else []
            else:
                continue
            kind = _classify(node, chain)
            if kind == TYPING_ONLY:
                continue
            for module in modules:
                if module in standard_library or module in FIRST_PARTY:
                    continue
                sites.append(
                    ImportSite(
                        module=module,
                        distribution=distribution_for(module),
                        kind=kind,
                        location=f"{_display_path(path, root)}:{node.lineno}",
                    )
                )
    return sites


def undeclared_imports(root: Path = APP_ROOT, pyproject_path: Path = PYPROJECT_PATH) -> dict[str, list[ImportSite]]:
    """Return the import sites whose distribution the project neither declares nor allowlists, keyed by distribution.

    A ``required`` site is reported even when the distribution is allowlisted: an allowlist says a code path degrades
    gracefully, which an unguarded import-time import does not.
    """
    declared = read_declared_contract(pyproject_path)
    findings: dict[str, list[ImportSite]] = {}
    for site in scan_imports(root):
        if site.kind == REQUIRED:
            satisfied = site.distribution in declared.base
        else:
            satisfied = (
                site.distribution in declared.base
                or site.distribution in declared.extras
                or site.distribution in OPTIONAL_IMPORT_ALLOWLIST
            )
        if not satisfied:
            findings.setdefault(site.distribution, []).append(site)
    return findings


def format_findings(findings: dict[str, list[ImportSite]]) -> str:
    """Render findings as an actionable failure message naming the first site of each distribution."""
    lines = []
    for distribution in sorted(findings):
        sites = findings[distribution]
        kinds = sorted({site.kind for site in sites})
        lines.append(
            f"  {distribution}: {len(sites)} import site(s), {'/'.join(kinds)}; first at {sites[0].location}"
            f" (imported as '{sites[0].module}')"
        )
    return "\n".join(lines)
