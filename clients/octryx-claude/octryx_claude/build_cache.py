"""A build the device already made for the same inputs is reused, not rebuilt (do not
rebuild everything every time).

rc3 flutter-bug c1b57069: the system test spent most of its 186 s in ``flutter build web``, and the hands-on test's
``serve`` built the same app once more. The platform names each stack's build artifacts as data (stacks.json
``build_artifacts``: the tool, its arguments, the output folder and the inputs); the launcher puts a small command of
that tool's name first on ``PATH`` for the pipeline and the hands-on test. A matching call (``flutter build web``)
computes the key, the SHA-256 over the inputs' paths and bytes, the arguments and the tool's own version file:

- **hit**: the stored output is cloned into place (APFS ``cp -c``, a copy elsewhere) with a fresh time, so a check
  "is the build newer than the sources" holds; the tool does not run;
- **miss**: the real tool runs; its output is stored under the key when it exits 0.

Only an exact key is reused. Every hit and miss is written to ``test-reports/build-cache.jsonl`` in the app folder
and goes up with the report. ``OCTRYX_NO_BUILD_CACHE=1`` turns it off (the nightly builds without it).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SPEC_ENV, REAL_ENV, ROOT_ENV, OFF_ENV = ("OCTRYX_BUILD_SPEC", "OCTRYX_BUILD_REAL", "OCTRYX_BUILD_CACHE_ROOT",
                                         "OCTRYX_NO_BUILD_CACHE")
LOG = "test-reports/build-cache.jsonl"
KEEP = 20  # stored outputs kept per device, newest first (a Flutter web build is some 30-60 MB)
SKIP_DIRS = {".dart_tool", "build", ".git", "node_modules", ".venv"}


def _cache_root() -> Path:
    home = os.environ.get("OCTRYX_CLAUDE_HOME") or str(Path.home() / ".octryx" / "claude")
    return Path(os.environ.get(ROOT_ENV) or Path(home) / "cache" / "build")


def shim_env(env: dict[str, str], specs: list[dict[str, Any]] | None) -> dict[str, str]:
    """``env`` with a command per artifact tool first on ``PATH`` (none without specs or with the cache off)."""
    tools = sorted({str(spec.get("tool")) for spec in specs or [] if spec.get("tool")})
    if not tools or env.get(OFF_ENV) == "1":
        return env
    shim = _cache_root() / "bin"
    shim.mkdir(parents=True, exist_ok=True)
    real: dict[str, str] = {}
    for tool in tools:
        found = shutil.which(tool, path=env.get("PATH", ""))
        if not found:
            continue
        real[tool] = found
        script = shim / tool
        content = f'#!/bin/sh\nexec "{sys.executable}" -m octryx_claude.build_cache "{tool}" "$@"\n'
        if not script.is_file() or script.read_text(encoding="utf-8") != content:
            partial = shim / f".{tool}.{os.getpid()}.tmp"
            partial.write_text(content, encoding="utf-8")
            partial.chmod(0o755)
            partial.replace(script)
    if not real:
        return env
    package = str(Path(__file__).resolve().parent.parent)
    return {**env, "PATH": os.pathsep.join([str(shim), env.get("PATH", "")]), SPEC_ENV: json.dumps(specs),
            REAL_ENV: json.dumps(real), "PYTHONPATH": os.pathsep.join(filter(None, [package,
                                                                                     env.get("PYTHONPATH")]))}


def _matching(tool: str, args: list[str], specs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for spec in specs:
        wanted = [str(item) for item in spec.get("args") or []]
        if spec.get("tool") == tool and args[:len(wanted)] == wanted:
            return spec
    return None


def _files(folder: Path, inputs: list[str]) -> list[Path]:
    found: list[Path] = []
    for item in inputs:
        path = folder / item
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            for root, dirs, names in os.walk(path):
                dirs[:] = sorted(name for name in dirs if name not in SKIP_DIRS)
                found += [Path(root) / name for name in sorted(names)]
    return found


def key_of(folder: Path, spec: dict[str, Any], args: list[str], real: str) -> str:
    """The SHA-256 over the inputs (path and bytes), the arguments that change the output and the tool's version."""
    digest = hashlib.sha256()
    ignored = {str(item) for item in spec.get("ignore_args") or []}
    digest.update(json.dumps([arg for arg in args if arg not in ignored]).encode())
    version = Path(real).resolve().parent.parent / "version"  # Flutter's SDK names its version there
    digest.update(version.read_bytes() if version.is_file() else Path(real).resolve().as_posix().encode())
    for path in _files(folder, [str(item) for item in spec.get("inputs") or []]):
        digest.update(path.relative_to(folder).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def _clone(source: Path, target: Path) -> None:
    shutil.rmtree(target, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    cloned = sys.platform == "darwin" and subprocess.run(["cp", "-cR", str(source), str(target)],
                                                          capture_output=True, check=False).returncode == 0
    if not cloned:
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(source, target)
    now = time.time()
    for root, _dirs, names in os.walk(target):
        for name in names:
            os.utime(Path(root) / name, (now, now))  # newer than the sources, like a fresh build


def _note(folder: Path, entry: dict[str, Any]) -> None:
    log = folder / LOG
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # the note is evidence of the reuse, never a reason to fail the build


def _prune(root: Path) -> None:
    stored = sorted((path for path in root.iterdir() if path.is_dir() and len(path.name) == 64),
                    key=lambda path: path.stat().st_mtime, reverse=True)
    for old in stored[KEEP:]:
        shutil.rmtree(old, ignore_errors=True)


def run(tool: str, args: list[str], folder: Path) -> int:
    """The tool's call, served from the cache when an exact key is stored."""
    specs = json.loads(os.environ.get(SPEC_ENV) or "[]")
    real = str(json.loads(os.environ.get(REAL_ENV) or "{}").get(tool) or "")
    spec = _matching(tool, args, specs) if real else None
    if spec is None:
        return subprocess.run([real or tool, *args], check=False).returncode
    started = time.monotonic()
    key = key_of(folder, spec, args, real)
    root = _cache_root()
    stored = root / key / "output"
    output = folder / str(spec["output"])
    if stored.is_dir():
        _clone(stored, output)
        os.utime(stored.parent)  # kept as recently used
        print(f"octryx build cache: hit {key[:12]} ({spec['output']} reused)", flush=True)
        _note(folder, {"result": "hit", "key": key, "command": " ".join([tool, *args]),
                       "seconds": round(time.monotonic() - started, 2)})
        return 0
    code = subprocess.run([real, *args], check=False).returncode
    if code == 0 and output.is_dir():
        partial = root / f".{key}.{os.getpid()}"
        _clone(output, partial / "output")
        shutil.rmtree(root / key, ignore_errors=True)
        partial.replace(root / key)
        _prune(root)
    _note(folder, {"result": "miss", "key": key, "command": " ".join([tool, *args]), "exit_code": code,
                   "seconds": round(time.monotonic() - started, 2)})
    return code


def read_notes(folder: Path) -> list[dict[str, Any]]:
    """The hits and misses of this folder's builds since the last read (the file is emptied)."""
    log = folder / LOG
    try:
        lines = log.read_text(encoding="utf-8").splitlines()
        log.unlink()
    except OSError:
        return []
    notes = []
    for line in lines[-50:]:
        try:
            notes.append(json.loads(line))
        except ValueError:
            continue
    return notes


if __name__ == "__main__":
    sys.exit(run(sys.argv[1], sys.argv[2:], Path.cwd()))
