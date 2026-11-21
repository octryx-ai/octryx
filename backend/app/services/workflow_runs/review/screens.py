"""Screenshots of the built app for the independent review: the review checks the UI.

Without them, the system tests saved a screenshot of every page, the author looked at them, and the
reviewer (text only) passed six stories without a finding while two screens were missing from the navigation. So the
reviewer sees the screens too, next to the specification's UI and design section.

- a server run: the working copy's ``test-reports/screenshots/`` (the system test rule's folder, git-ignored);
- a device run: the launcher uploads that folder's images at Stop of a changing phase (``POST
  /sessions/screenshots``), bound to the pass (node and entry), before the verification that ends the phase. They
  are kept under the server working copy's ``.git`` folder, so they are never part of the pushed tree; a run whose
  working copy is only on the device (no server copy) keeps them in the installation's data folder
  (``<artifact_store_dir>/../run-screens/<run>/<node>``). Otherwise every device run's
  hands-on screenshots were refused "no_working_copy" and lost, ``local_path`` being a folder on the Mac.

Bounded: images only (PNG, JPEG, WebP by their magic bytes), at most :data:`MAX_SCREENS` per pass, each at most
:data:`MAX_BYTES`; newest first.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_SCREENS = 200  # a guard against a runaway folder, not a cut: a real story has far fewer
MAX_BYTES = 8_000_000
SERVER_FOLDER = ("test-reports", "screenshots")
_STORE = ("octryx-screens",)
_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_ENTRY_FILE = ".entry"


@dataclass(frozen=True, slots=True)
class Screen:
    name: str
    media_type: str
    data: bytes


def media_type(data: bytes) -> str:
    """The image type by its magic bytes, ``""`` for anything else."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _root(run: Any) -> Path | None:
    local = str(dict(run.context or {}).get("local_path") or "")
    root = Path(local) if local else None
    return root if root is not None and (root / ".git").is_dir() else None


def _data_store(run: Any, node_id: str) -> Path | None:
    from ....config import get_settings

    run_id = _NAME.sub("_", str(getattr(run, "id", "") or ""))[:64]
    if not run_id:
        return None
    base = Path(get_settings().artifact_store_dir).expanduser().resolve().parent
    return base / "run-screens" / run_id / _NAME.sub("_", node_id)[:80]


def _store(run: Any, node_id: str) -> Path | None:
    root = _root(run)
    if root is not None:
        return root.joinpath(".git", *_STORE, _NAME.sub("_", node_id)[:80])
    return _data_store(run, node_id)


def safe_name(name: str) -> str:
    base = _NAME.sub("_", Path(str(name or "")).name).strip("._")[:120]
    return base or "screen"


def store(run: Any, *, node_id: str, entry: Any, name: str, data: bytes) -> str:
    """Keep one uploaded screenshot of the pass; ``""`` when kept, else the refusal reason."""
    if len(data) > MAX_BYTES:
        return "too_large"
    if not media_type(data):
        return "not_an_image"
    folder = _store(run, node_id)
    if folder is None:
        return "no_working_copy"
    marker = folder / _ENTRY_FILE
    if folder.is_dir() and (not marker.is_file() or marker.read_text() != str(entry)):
        shutil.rmtree(folder)  # an earlier pass's screens: never reviewed with this pass
    folder.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(entry))
    kept = [path for path in folder.iterdir() if path.name != _ENTRY_FILE]
    target = folder / safe_name(name)
    if not target.exists() and len(kept) >= MAX_SCREENS:
        return "too_many"
    target.write_bytes(data)
    return ""


def collect(run: Any, node_id: str) -> list[Screen]:
    """The pass's screenshots, newest first: uploaded by the device, else the server working copy's folder."""
    root = _root(run)
    uploaded = _store(run, node_id)
    folders = [uploaded] if uploaded is not None and uploaded.is_dir() else []
    if root is not None:
        folders.append(root.joinpath(*SERVER_FOLDER))
    for folder in folders:
        if not folder.is_dir():
            continue
        files = sorted((path for path in folder.iterdir() if path.is_file() and path.name != _ENTRY_FILE),
                       key=lambda path: path.stat().st_mtime, reverse=True)
        screens = []
        for path in files:
            if path.stat().st_size > MAX_BYTES:
                continue
            data = path.read_bytes()
            kind = media_type(data)
            if kind:
                screens.append(Screen(path.name, kind, data))
            if len(screens) >= MAX_SCREENS:
                break
        if screens:
            return sorted(screens, key=lambda screen: screen.name)
    return []


_TEST_FILE = re.compile(r"(^|/)(test_[^/]+|[^/]+[._-](spec|test)\.[^/]+|[^/]+_test\.[^/]+)$", re.IGNORECASE)
_SKIP_DIRS = frozenset({".git", "node_modules", "dist", "build", ".venv", "venv", "__pycache__", "test-reports",
                        "coverage", ".next", "target"})
_GENERIC = frozenset({"src", "app", "apps", "lib", "libs", "test", "tests", "e2e", "spec", "specs", "docs", "doc",
                      "scripts", "public", "static", "assets", "frontend", "backend", "packages", "web", "client",
                      "server", "system", "page", "pages", "screen", "screens", "screenshot", "screenshots",
                      "view", "views", "component", "components"})
_TOKEN = re.compile(r"[a-z0-9]+")


def of_change(screens: list[Screen], *, diff: str, changed: tuple[str, ...], root: Path | None) -> list[Screen]:
    """The screenshots that belong to this change: a screenshot is dropped only when another part of the repository
    claims it and this change does not (if unsure, keep).

    Example: two apps share one repository and one system test folder; the
    reviewer was shown the other app's ``members-page.png`` and wrote findings against this story. A screenshot
    is another part's when its name carries another app's folder name, or when a test in another app's folder (a
    top-level folder the change does not touch) names its file; it is this change's when the change names it, its
    name shares a word with a test file the change touches, or carries the changed app's folder name."""
    if not screens or not changed:
        return screens
    ours = _words_of(changed)
    added = "\n".join(line for line in diff.splitlines() if line.startswith("+")).lower()
    foreign_apps = _foreign_apps(root, changed)
    foreign_tests = _foreign_tests(root, foreign_apps) if root is not None else []
    kept = []
    for screen in screens:
        stem = Path(screen.name).stem.lower()
        words = set(_TOKEN.findall(stem)) - _GENERIC
        mine = bool(words & ours) or (stem and re.search(rf"(?<![a-z0-9]){re.escape(stem)}(?![a-z0-9])", added))
        theirs = bool(words & {app.lower() for app in foreign_apps}) or any(
            screen.name.lower() in text for text in foreign_tests)
        if mine or not theirs:
            kept.append(screen)
    return kept


def _words_of(changed: tuple[str, ...]) -> set[str]:
    """The words of the changed test files' names and of the changed apps' folders."""
    words: set[str] = set()
    for path in changed:
        parts = path.lower().split("/")
        if len(parts) > 1 and parts[0] not in _GENERIC:
            words.add(parts[0])
        if _TEST_FILE.search(path):
            words |= {word for word in _TOKEN.findall(Path(parts[-1]).name.split(".")[0])
                      if len(word) >= 4} - _GENERIC - {"test", "spec"}
    return words


def _foreign_apps(root: Path | None, changed: tuple[str, ...]) -> set[str]:
    """Top-level folders of the repository the change does not touch (other apps in a multi-app repository)."""
    if root is None:
        return set()
    touched = {path.split("/")[0].lower() for path in changed}
    try:
        folders = [path.name for path in root.iterdir() if path.is_dir()]
    except OSError:
        return set()
    return {name for name in folders if name.lower() not in touched and name.lower() not in _GENERIC
            and name not in _SKIP_DIRS and not name.startswith(".") and len(name) >= 4}


def _foreign_tests(root: Path, apps: set[str]) -> list[str]:
    """The text of every test file in another app's folder (one the change does not touch)."""
    texts: list[str] = []
    for folder in sorted(apps):
        for path in _test_files(root / folder):
            try:
                texts.append(path.read_text(encoding="utf-8", errors="replace").lower())
            except OSError:
                continue
    return texts


def _test_files(root: Path) -> list[Path]:
    found: list[Path] = []
    stack = [root]
    while stack:
        folder = stack.pop()
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in _SKIP_DIRS and not entry.is_symlink():
                    stack.append(entry)
            elif _TEST_FILE.search(entry.name) and entry.stat().st_size <= MAX_BYTES:
                found.append(entry)
    return found


def reviewed_phase(run: Any, graph: Any) -> str:
    """The phase whose screenshots the person's decision card shows: the ``config.phase`` of the review node (the
    changing phase the review checks, e.g. ``implement``), never the review node's own id; the screens are kept per
    pass under that phase id and cleared on a new entry, so :func:`collect` returns only the current pass. The review
    node is the one that gave the run's last verdict, else the first review node of the graph."""
    reviewed = str(dict(dict(run.context or {}).get("review") or {}).get("node_id") or "")
    nodes = [graph.nodes[node_id] for node_id in (graph.order or list(graph.nodes)) if node_id in graph.nodes]
    reviews = [node for node in nodes if node.kind == "review" and dict(node.config or {}).get("phase")]
    chosen = next((node for node in reviews if node.id == reviewed), reviews[0] if reviews else None)
    if chosen is None:
        return ""
    # The pipeline's screenshots when the review takes them from there (``screens_node``), else the phase's.
    return str(chosen.config.get("screens_node") or chosen.config["phase"])


__all__ = ["MAX_BYTES", "MAX_SCREENS", "Screen", "collect", "media_type", "of_change", "reviewed_phase", "safe_name",
           "store"]
