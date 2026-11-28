"""Code a device job reads, sent as an archive the device fetches with its own token; results come back the same way
(built once for the check proof of From Correction to Check and the review bot's scan)."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import secrets
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

MAX_FILE = 2_000_000
MAX_TOTAL = 50_000_000
TTL_SECONDS = 900
GIT_TIMEOUT = 60


@dataclass
class Archive:
    name: str
    data: bytes
    sha256: str
    bytes: int
    skipped: list[str] = field(default_factory=list)


def _safe(path: str) -> str:
    text = str(path or "").replace("\\", "/")
    pure = PurePosixPath(text)
    if not text or pure.is_absolute() or ".." in pure.parts or text.startswith("~"):
        return ""
    return pure.as_posix() if pure.as_posix() != "." else ""  # PurePosixPath already drops a leading "./"


def build_archive(entries: Iterable[tuple[str, bytes]], *, name: str, max_file: int = MAX_FILE,
                  max_total: int = MAX_TOTAL) -> Archive:
    kept: dict[str, bytes] = {}
    skipped: list[str] = []
    total = 0
    for raw, content in sorted(entries, key=lambda item: str(item[0])):
        path = _safe(raw)
        if not path or path in kept or len(content) > max_file or total + len(content) > max_total:
            skipped.append(str(raw))
            continue
        kept[path] = content
        total += len(content)
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for path, content in kept.items():
            info = tarfile.TarInfo(path)
            info.size, info.mode, info.mtime, info.uid, info.gid, info.uname, info.gname = (
                len(content), 0o644, 0, 0, 0, "", "")
            archive.addfile(info, io.BytesIO(content))
    zipped = io.BytesIO()
    with gzip.GzipFile(fileobj=zipped, mode="wb", mtime=0) as stream:
        stream.write(tar_bytes.getvalue())
    data = zipped.getvalue()
    return Archive(name=name, data=data, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), skipped=skipped)


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=GIT_TIMEOUT,
                          check=True).stdout


def build_from_git(repo: Path, ref: str, *, name: str, paths: list[str] | None = None, max_file: int = MAX_FILE,
                   max_total: int = MAX_TOTAL) -> Archive:
    listing = _git(repo, "ls-tree", "-r", "-l", "-z", ref, "--", *(paths or [])).split(b"\0")
    entries: list[tuple[str, bytes]] = []
    skipped: list[str] = []
    for line in filter(None, listing):
        meta, _tab, raw_path = line.partition(b"\t")
        mode, kind, blob, size = meta.decode().split()
        path = raw_path.decode("utf-8", "replace")
        if kind != "blob" or mode not in ("100644", "100755") or not size.isdigit() or int(size) > max_file:
            skipped.append(path)
            continue
        entries.append((path, _git(repo, "cat-file", "blob", blob)))
    archive = build_archive(entries, name=name, max_file=max_file, max_total=max_total)
    archive.skipped = sorted([*skipped, *archive.skipped])
    return archive


def store_dir() -> Path:
    configured = os.environ.get("OCTRYX_DEVICE_ARCHIVE_DIR")
    folder = Path(configured) if configured else Path(tempfile.gettempdir()) / "octryx-device-archives"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _prune(folder: Path, now: float) -> None:
    for meta in folder.glob("*.json"):
        try:
            expired = float(json.loads(meta.read_text(encoding="utf-8")).get("expires_at") or 0) < now
        except (OSError, ValueError):
            expired = True
        if expired:
            meta.with_suffix(".bin").unlink(missing_ok=True)
            meta.unlink(missing_ok=True)


def _keep(data: bytes, meta: dict, ttl_seconds: int) -> str:
    folder = store_dir()
    now = time.time()
    _prune(folder, now)
    ident = secrets.token_urlsafe(24)
    (folder / f"{ident}.bin").write_bytes(data)
    (folder / f"{ident}.json").write_text(json.dumps({**meta, "expires_at": now + ttl_seconds}), encoding="utf-8")
    return ident


def offer(archive: Archive, *, device_id: str, ttl_seconds: int = TTL_SECONDS) -> dict:
    ident = _keep(archive.data, {"device_id": device_id, "kind": "archive", "name": archive.name,
                                 "sha256": archive.sha256}, ttl_seconds)
    return {"name": archive.name, "url": f"/api/v1/devices/archives/{ident}", "sha256": archive.sha256,
            "bytes": archive.bytes, "skipped": list(archive.skipped)}


def _read(ident: str, device_id: str, kind: str) -> bytes | None:
    if not ident.replace("-", "").replace("_", "").isalnum():
        return None
    folder = store_dir()
    _prune(folder, time.time())
    try:
        meta = json.loads((folder / f"{ident}.json").read_text(encoding="utf-8"))
        data = (folder / f"{ident}.bin").read_bytes()
    except (OSError, ValueError):
        return None
    return data if meta.get("device_id") == device_id and meta.get("kind") == kind else None


def fetch(ident: str, device_id: str) -> bytes | None:
    return _read(ident, device_id, "archive")


def accept_upload(data: bytes, *, device_id: str, name: str, max_total: int = MAX_TOTAL,
                  ttl_seconds: int = 3600) -> dict | str:
    if len(data) > max_total:
        return f"the upload is {len(data)} bytes, over the limit of {max_total}"
    digest = hashlib.sha256(data).hexdigest()
    ident = _keep(data, {"device_id": device_id, "kind": "upload", "name": name[:120], "sha256": digest}, ttl_seconds)
    return {"id": ident, "sha256": digest, "bytes": len(data)}


def read_upload(ident: str, device_id: str) -> bytes | None:
    return _read(ident, device_id, "upload")


__all__ = ["Archive", "accept_upload", "build_archive", "build_from_git", "fetch", "offer", "read_upload",
           "store_dir"]
