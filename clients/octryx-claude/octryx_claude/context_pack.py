"""The context pack: what a run's writing phase most likely touches, built from the checkout without a model and
put in front of the phase's first prompt, the same for Claude Code and Codex (the offer's ``context_pack``)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from .context_pack_match import callers, tests_for
from .context_pack_rank import Ranking, rank
from .context_pack_routes import Route, fastapi_routes
from .context_pack_structure import Structure, read_structure

MAX_CHARS = 3000
MAX_SYMBOLS, MAX_CALLERS, MAX_ROUTES, MAX_TESTS, MAX_FILES = 8, 3, 6, 6, 10
CACHE_DIR = "context-pack"
SHOWN_FILE = "shown.json"
KEEP_CACHED = 8
KEEP_SHOWN = 200
EVENT_KIND = "context_pack"
FOLLOWS = "Your task follows."


def _git(root: str, *args: str) -> bytes:
    try:
        out = subprocess.run(["git", "-C", root, *args], capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return b""
    return out.stdout if out.returncode == 0 else b""


def fingerprint(root: str, app_folder: str) -> str:
    folder = app_folder.strip("/") or "."
    digest = hashlib.sha256(_git(root, "rev-parse", f"HEAD:{folder}" if folder != "." else "HEAD^{tree}"))
    for entry in _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", folder).split(b"\0"):
        name = entry[3:].decode("utf-8", "replace")
        digest.update(entry)
        try:
            stat = (Path(root) / name).stat()
            digest.update(f"{stat.st_mtime_ns}:{stat.st_size}".encode())
        except OSError:
            continue
    return digest.hexdigest()[:24]


# Tracked and new files (not ignored ones): the pack also knows what the run already added.
def _files(root: str, app_folder: str) -> list[str]:
    listed = _git(root, "ls-files", "-z", "-co", "--exclude-standard", "--", app_folder.strip("/") or ".")
    return sorted({name for name in listed.decode("utf-8", "replace").split("\0") if name})


def _facts(state_root: Path, root: str, app_folder: str) -> tuple[Structure, list[Route], str, bool]:
    key = fingerprint(root, app_folder)
    folder = state_root / CACHE_DIR
    cached = folder / f"{key}.json"
    try:
        data = json.loads(cached.read_text(encoding="utf-8"))
        return Structure.from_json(data["structure"]), [tuple(item) for item in data["routes"]], key, True
    except (OSError, ValueError, KeyError, TypeError):
        pass
    files = _files(root, app_folder)
    structure = read_structure(root, files)
    routes = fastapi_routes(root, files)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps({"structure": structure.to_json(), "routes": routes}), encoding="utf-8")
        for old in sorted(folder.glob("*.json"), key=lambda path: path.stat().st_mtime)[:-KEEP_CACHED]:
            old.unlink(missing_ok=True)
    except OSError:
        pass
    return structure, routes, key, False


def _symbol_line(structure: Structure, file: str, name: str, line: int) -> str:
    text = f"- `{name}` {file}:{line}"
    found = callers(structure, file, name, MAX_CALLERS)
    if found:
        text += "; called from " + ", ".join(f"{call_file}:{call_line}" + (f" `{inside}`" if inside else "")
                                             for call_file, call_line, inside in found)
    return text


def _route_line(route: Route) -> str:
    file, line, method, path, handler, guards = route
    guarded = f" [dependencies: {', '.join(guards)}]" if guards else " [no dependencies]"
    return f"- {method} {path} -> `{handler}` {file}:{line}{guarded}"


def _sections(structure: Structure, routes: list[Route], ranking: Ranking) -> list[tuple[str, list[str]]]:
    chosen = {(file, name) for _score, file, name, _line in ranking.symbols}
    shown_routes = [route for route in routes if (route[0], route[4]) in chosen][:MAX_ROUTES]
    tests = list(dict.fromkeys([*ranking.tests, *(test for _score, file, name, _line in ranking.symbols
                                                   for test in tests_for(structure, file, name))]))[:MAX_TESTS]
    return [("Likely affected symbols (name, definition, call sites):",
             [_symbol_line(structure, file, name, line) for _score, file, name, line in ranking.symbols]),
            ("Routes they serve (method, path, handler, the dependencies that guard it):",
             [_route_line(route) for route in shown_routes]),
            ("Tests that match the item or import these symbols:", [f"- {test}" for test in tests]),
            ("Files:", [f"- {file}" + (f" ({why})" if why else "") for _score, file, why in ranking.files])]


def render(item: dict[str, Any], structure: Structure, routes: list[Route]) -> tuple[str, dict[str, int]]:
    ranking = rank(structure, routes, item, {"symbols": MAX_SYMBOLS, "files": MAX_FILES})
    if not ranking.confident or not (ranking.symbols or ranking.files or ranking.tests):
        # A weak match sends nothing: a pack that misses the target costs reads and tokens.
        return "", {"symbols": 0, "routes": 0, "tests": 0, "files": 0, "cut": int(structure.cut), "confident": 0}
    sections = _sections(structure, routes, ranking)
    lines = ["Context pack (built from the checkout by a script, not a model; read a file before you change it; "
             "the test and lint commands are in your phase brief):"]
    for head, rows in sections:
        if rows:
            lines += [head, *rows]
    text, cut = "", False
    for line in lines:
        if len(text) + len(line) + 1 > MAX_CHARS:
            cut = True
            break
        text += line + "\n"
    stats = {"symbols": len(ranking.symbols), "routes": len(sections[1][1]), "tests": len(sections[2][1]),
             "files": len(ranking.files), "cut": int(cut or structure.cut), "confident": 1}
    return text.rstrip("\n"), stats


def _first_time(state_root: Path, key: str) -> bool:
    path = state_root / CACHE_DIR / SHOWN_FILE
    try:
        shown = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        shown = {}
    if not isinstance(shown, dict):
        shown = {}
    if key in shown:
        return False
    shown[key] = int(time.time())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(sorted(shown.items(), key=lambda item: item[1])[-KEEP_SHOWN:])),
                        encoding="utf-8")
    except OSError:
        pass
    return True


def build(state_root: Path, folder: str, request: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    started = time.monotonic()
    app_folder = str(request.get("app_folder") or ".")
    structure, routes, key, cached = _facts(state_root, folder, app_folder)
    text, stats = render(dict(request.get("item") or {}), structure, routes)
    event = {"kind": EVENT_KIND, "phase": str(request.get("phase") or ""), "fingerprint": key, "cached": cached,
             "indexed_files": len(structure.files), "definitions": len(structure.definitions),
             "fastapi_routes": len(routes), "chars": len(text), "ms": int((time.monotonic() - started) * 1000),
             **stats, "text": text}
    return text, event


def with_context_pack(state_root: Path, offer: dict[str, Any], session_key: str) -> tuple[str, dict[str, Any] | None]:
    request = offer.get("context_pack")
    prompt = str(offer.get("prompt") or "")
    if not isinstance(request, dict) or not offer.get("folder"):
        return prompt, None
    if not _first_time(state_root, f"{offer.get('workflow_run')}:{request.get('phase')}:{session_key}"):
        return prompt, None
    try:
        text, event = build(state_root, str(offer["folder"]), request)
    except Exception as error:  # noqa: BLE001 - the turn runs without a pack, and the event says why
        return prompt, {"kind": EVENT_KIND, "phase": str(request.get("phase") or ""), "error": type(error).__name__}
    return (f"{text}\n\n{FOLLOWS}\n\n{prompt}" if text else prompt), event


__all__ = ["EVENT_KIND", "build", "fingerprint", "render", "with_context_pack"]
