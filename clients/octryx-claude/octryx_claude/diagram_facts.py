"""The app's draw.io diagrams at the end of a changing phase: the launcher exports each diagram's PNG
with the draw.io CLI outside Claude Code's sandbox, before the phase's change is taken, so the PNG is part of the
reviewed and pushed change; then it reports what the platform judges (``code_style.diagrams``):

- every ``*.drawio`` in the style's ``folder`` (``docs/diagrams``) of any app folder: valid draw.io XML or why not;
- its PNG in ``images`` (``docs/images/<name>.png``): ``exported`` now, ``current`` (newer than the diagram),
  ``stale`` (older, and no CLI to export), ``missing_tool`` (no PNG and no CLI) or ``export_failed``;
- whether the app's README or a docs page references the PNG;
- the box labels that are no name in the app's code (module, class, file or screen names).

A missing CLI never stops anything: the ``.drawio`` is committed without its PNG and the platform warns.
"""

from __future__ import annotations

import base64
import platform
import re
import shutil
import subprocess
import urllib.parse
import zlib
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

MAX_DIAGRAMS = 20
EXPORT_TIMEOUT = 120
EXPORT_ATTEMPTS = 2
MAX_LABELS = 40
CODE_SUFFIXES = (".dart", ".ts", ".tsx", ".js", ".jsx", ".py", ".kt", ".java", ".swift", ".go", ".rs", ".vue",
                 ".svelte", ".cs")
SKIPPED = {".git", "node_modules", "build", ".dart_tool", ".venv", "venv", "dist", ".next", "target", "Pods"}
MAC_CLI = "/Applications/draw.io.app/Contents/MacOS/draw.io"
_TAG = re.compile(r"<[^>]+>")


def drawio_cli() -> str | None:
    return shutil.which("drawio") or shutil.which("draw.io") or (MAC_CLI if Path(MAC_CLI).is_file() else None)


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _models(root: ElementTree.Element) -> list[ElementTree.Element]:
    """The ``mxGraphModel`` of every page, also of a compressed page (base64, raw deflate, URL-encoded)."""
    models = [root] if root.tag == "mxGraphModel" else list(root.iter("mxGraphModel"))
    for diagram in root.iter("diagram"):
        text = (diagram.text or "").strip()
        if text and not len(diagram):
            xml = urllib.parse.unquote(zlib.decompress(base64.b64decode(text), -15).decode("utf-8"))
            models.append(ElementTree.fromstring(xml))
    return models


def labels(path: Path) -> list[str]:
    """The diagram's box labels (first line, tags removed); raises ``ValueError`` when it is no draw.io XML."""
    try:
        root = ElementTree.parse(path).getroot()
        models = _models(root)
    except (ElementTree.ParseError, ValueError, zlib.error, UnicodeDecodeError) as error:
        raise ValueError(str(error)[:200]) from None
    if root.tag not in ("mxfile", "mxGraphModel") or not models:
        raise ValueError("no mxfile / mxGraphModel")
    found: list[str] = []
    for model in models:
        for cell in model.iter("mxCell"):
            if cell.get("vertex") != "1":
                continue
            value = _TAG.sub("\n", (cell.get("value") or "").replace("<br>", "\n")).strip()
            first = value.splitlines()[0].strip() if value else ""
            if len(first) > 2 and first not in found:
                found.append(first)
    return found[:MAX_LABELS]


def _code_names(app: Path) -> set[str]:
    names: set[str] = set()
    stack = [app]
    while stack:
        folder = stack.pop()
        for entry in sorted(folder.iterdir()) if folder.is_dir() else []:
            if entry.is_dir():
                if entry.name not in SKIPPED and not entry.name.startswith("."):
                    stack.append(entry)
            elif entry.suffix in CODE_SUFFIXES:
                names.add(_squash(entry.stem))
                try:
                    text = entry.read_text(encoding="utf-8", errors="replace")[:400_000]
                except OSError:
                    continue
                names.update(_squash(word) for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text))
    return names


def _unmatched(found: list[str], names: set[str]) -> list[str]:
    missing = []
    for label in found:
        key = _squash(label)
        if key and not any(key in name for name in names):
            missing.append(label)
    return missing


def _referenced(app: Path, png: Path) -> bool:
    name = png.name
    docs = [app / "README.md", *(app / "docs").rglob("*.md")] if (app / "docs").is_dir() else [app / "README.md"]
    return any(page.is_file() and name in page.read_text(encoding="utf-8", errors="replace") for page in docs)


def _export_once(cli: str, source: Path, target: Path) -> str:
    try:
        done = subprocess.run([cli, "-x", "-f", "png", "--scale", "2", "-o", str(target), str(source)],
                              capture_output=True, text=True, timeout=EXPORT_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return str(error)[:300]
    if done.returncode != 0 or not target.is_file():
        return (done.stderr or done.stdout or f"exit {done.returncode}").strip()[-300:]
    return ""


def _export(cli: str, source: Path, target: Path) -> str:
    """Export the PNG; one more attempt when the CLI ends without it.

    The draw.io CLI is an Electron app: on a busy machine it now and then ended without writing the PNG, and the next
    run of the same export succeeded. A second failure is reported with its own words (``export_failed``)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    problem = ""
    for _attempt in range(EXPORT_ATTEMPTS):
        problem = _export_once(cli, source, target)
        if not problem:
            return ""
    return problem


def diagram_facts(root: Path, diagrams: dict[str, Any] | None) -> dict[str, Any] | None:
    """What the platform judges, after exporting every PNG that is missing or older than its diagram."""
    config = dict(diagrams or {})
    if not config or config.get("enabled") is False:
        return None
    folder, images = str(config.get("folder") or "docs/diagrams"), str(config.get("images") or "docs/images")
    sources = sorted(path for path in root.glob(f"**/{folder}/*.drawio")
                     if not set(path.relative_to(root).parts) & SKIPPED)[:MAX_DIAGRAMS]
    if not sources:
        return None
    cli = drawio_cli()
    files = []
    names_of: dict[Path, set[str]] = {}
    for source in sources:
        app = source.parents[len(Path(folder).parts)]
        relative = source.relative_to(root).as_posix()
        png = app / images / f"{source.stem}.png"
        item: dict[str, Any] = {"path": relative, "png": png.relative_to(root).as_posix()}
        try:
            found = labels(source)
        except ValueError as error:
            files.append({**item, "valid": False, "error": str(error)})
            continue
        fresh = png.is_file() and png.stat().st_mtime >= source.stat().st_mtime
        if fresh:
            state = "current"
        elif cli is None:
            state = "stale" if png.is_file() else "missing_tool"
        else:
            problem = _export(cli, source, png)
            state, item = ("export_failed", {**item, "error": problem}) if problem else ("exported", item)
        if app not in names_of:
            names_of[app] = _code_names(app)
        files.append({**item, "valid": True, "png_state": state,
                      "referenced": _referenced(app, png) if png.is_file() else False,
                      "unmatched": _unmatched(found, names_of[app])})
    return {"tool": "present" if cli else "missing", "os": platform.system(), "files": files}


__all__ = ["diagram_facts", "drawio_cli", "labels"]
