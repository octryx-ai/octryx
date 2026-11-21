"""The octryx-claude package the platform serves to its installers.

The wheel is built in-process from the client sources shipped with the platform
(``clients/octryx-claude``), so the served client always matches this platform build. The build is
deterministic: fixed file order and timestamps, so the same sources give the same bytes, the same
sha256 and the same version. The version is the package's ``__version__`` plus a local segment of
the source hash (``0.2.0+1a2b3c4d5e6f``): every source change is a new version with a new sha256, which the
installer and the launcher's self-update on start compare exactly, so each deploy with changed client code reaches
installed copies at their next start (the Dockerfile copies these sources into the image).

Contents: the ``octryx_claude`` package (no tests), the platform scripts the transcript digest and the full
transcript upload reuse (``backend/scripts``: the two session-ingest scripts and ``transcript_secrets``, as
``octryx_claude/_platform_scripts``) and the
metadata from the client's ``pyproject.toml`` (name, Python requirement, pinned dependencies,
console script). Stdlib only: the installer tests import it without the app.
"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path

CLIENT_DIR_ENV = "OCTRYX_CLIENT_DIR"
PACKAGE = "octryx_claude"
VENDORED_DIR = "_platform_scripts"
PACKAGED = ("*.py", "*.json")
VENDORED_SCRIPTS = ("ingest_claude_session.py", "mcp_session_ingest_common.py", "transcript_secrets.py",
                    "secret_patterns.py")
WHEEL_TAG = "py3-none-any"
SOURCE_HASH_CHARS = 12
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
_VERSION_LINE = re.compile(r'^__version__\s*=\s*"([0-9]+(?:\.[0-9]+){1,3}(?:(?:a|b|rc)[0-9]+)?)"\s*$', re.MULTILINE)
_REPO_ROOT = Path(__file__).resolve().parents[4]


class ClientArtifactError(Exception):
    """The package cannot be built; ``code`` is fixed (``octryx_client_source_missing``, ...)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ClientArtifact:
    version: str
    filename: str
    sha256: str
    content: bytes
    requires_python: str


def default_client_dir() -> Path:
    override = os.environ.get(CLIENT_DIR_ENV, "").strip()
    return Path(override) if override else _REPO_ROOT / "clients" / "octryx-claude"


def default_scripts_dir() -> Path:
    return _REPO_ROOT / "backend" / "scripts"


def _packaged(package_dir: Path) -> list[Path]:
    """The package's modules and its data files (``os_junk.json``: read by the launcher and by the platform)."""
    return [path for pattern in PACKAGED for path in package_dir.rglob(pattern)]


def _sources(client_dir: Path, scripts_dir: Path) -> list[tuple[str, bytes]]:
    """``(archive path, bytes)`` of every packaged file, sorted by path."""
    package_dir = client_dir / PACKAGE
    if not package_dir.is_dir():
        raise ClientArtifactError("octryx_client_source_missing")
    files = [
        (f"{PACKAGE}/{path.relative_to(package_dir).as_posix()}", path.read_bytes())
        for path in _packaged(package_dir)
        if "__pycache__" not in path.parts and VENDORED_DIR not in path.relative_to(package_dir).parts
    ]
    for name in VENDORED_SCRIPTS:
        script = scripts_dir / name
        if not script.is_file():
            raise ClientArtifactError("octryx_client_platform_script_missing")
        files.append((f"{PACKAGE}/{VENDORED_DIR}/{name}", script.read_bytes()))
    return sorted(files)


def _project(client_dir: Path) -> dict:
    try:
        project = tomllib.loads((client_dir / "pyproject.toml").read_text(encoding="utf-8")).get("project")
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ClientArtifactError("octryx_client_pyproject_invalid") from exc
    if not isinstance(project, dict) or not project.get("name") or not project.get("requires-python"):
        raise ClientArtifactError("octryx_client_pyproject_invalid")
    return project


def _base_version(files: list[tuple[str, bytes]]) -> str:
    init = dict(files).get(f"{PACKAGE}/__init__.py", b"").decode("utf-8")
    match = _VERSION_LINE.search(init)
    if not match:
        raise ClientArtifactError("octryx_client_version_missing")
    return match.group(1)


def source_hash(files: list[tuple[str, bytes]], pyproject: bytes) -> str:
    digest = hashlib.sha256()
    for name, content in [("pyproject.toml", pyproject), *files]:
        digest.update(name.encode("utf-8") + b"\0" + hashlib.sha256(content).digest())
    return digest.hexdigest()


def _record_hash(content: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode("ascii").rstrip("=")


def _metadata(project: dict, version: str) -> bytes:
    lines = [
        "Metadata-Version: 2.1",
        f"Name: {project['name']}",
        f"Version: {version}",
        f"Summary: {project.get('description', '')}",
        f"Requires-Python: {project['requires-python']}",
        *(f"Requires-Dist: {dependency}" for dependency in project.get("dependencies", [])),
    ]
    # Optional extras (``octryx-claude[pet]``, the tray icon's pystray and Pillow): without these lines an install
    # of ``octryx-claude[pet]`` from the served wheel would silently bring nothing.
    for extra, dependencies in sorted(dict(project.get("optional-dependencies") or {}).items()):
        lines.append(f"Provides-Extra: {extra}")
        lines += [f'Requires-Dist: {dependency} ; extra == "{extra}"' for dependency in dependencies]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _entry_points(project: dict) -> bytes:
    scripts = project.get("scripts") or {}
    lines = ["[console_scripts]", *(f"{name} = {target}" for name, target in sorted(scripts.items()))]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _wheel_bytes(entries: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            info = zipfile.ZipInfo(name, date_time=_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return buffer.getvalue()


def build_artifact(client_dir: Path | None = None, scripts_dir: Path | None = None) -> ClientArtifact:
    client_dir = client_dir or default_client_dir()
    scripts_dir = scripts_dir or default_scripts_dir()
    files = _sources(client_dir, scripts_dir)
    project = _project(client_dir)
    pyproject = (client_dir / "pyproject.toml").read_bytes()
    version = f"{_base_version(files)}+{source_hash(files, pyproject)[:SOURCE_HASH_CHARS]}"
    distribution = re.sub(r"[-_.]+", "_", str(project["name"])).lower()
    dist_info = f"{distribution}-{version}.dist-info"
    entries = [
        *files,
        (f"{dist_info}/METADATA", _metadata(project, version)),
        (f"{dist_info}/WHEEL", (f"Wheel-Version: 1.0\nGenerator: octryx\nRoot-Is-Purelib: true\n"
                                f"Tag: {WHEEL_TAG}\n").encode()),
        (f"{dist_info}/entry_points.txt", _entry_points(project)),
    ]
    record_lines = [f"{name},{_record_hash(content)},{len(content)}" for name, content in entries]
    record_lines.append(f"{dist_info}/RECORD,,")
    entries.append((f"{dist_info}/RECORD", ("\n".join(record_lines) + "\n").encode("utf-8")))
    content = _wheel_bytes(entries)
    return ClientArtifact(
        version=version,
        filename=f"{distribution}-{version}-{WHEEL_TAG}.whl",
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
        requires_python=str(project["requires-python"]),
    )


_CACHE: dict[tuple, ClientArtifact] = {}


def _signature(client_dir: Path, scripts_dir: Path) -> tuple:
    paths = [client_dir / "pyproject.toml", *sorted(_packaged(client_dir / PACKAGE)),
             *(scripts_dir / name for name in VENDORED_SCRIPTS)]
    stats = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            stats.append((str(path), None))
            continue
        stats.append((str(path), stat.st_mtime_ns, stat.st_size))
    return (str(client_dir), str(scripts_dir), tuple(stats))


def current_artifact(client_dir: Path | None = None, scripts_dir: Path | None = None) -> ClientArtifact:
    """The served package; rebuilt only when a source file changed (mtime or size)."""
    client_dir = client_dir or default_client_dir()
    scripts_dir = scripts_dir or default_scripts_dir()
    if not (client_dir / PACKAGE).is_dir():
        raise ClientArtifactError("octryx_client_source_missing")
    key = _signature(client_dir, scripts_dir)
    cached = _CACHE.get(key)
    if cached is None:
        cached = build_artifact(client_dir, scripts_dir)
        _CACHE.clear()
        _CACHE[key] = cached
    return cached
