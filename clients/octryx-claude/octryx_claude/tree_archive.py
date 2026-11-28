"""A device job's code arrives as an archive the device fetches with its own token; a large result goes back as an
upload (the check proof and the review bot's scan; server ``services/devices/tree_archive``)."""

from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

TIMEOUT = 120.0
UPLOAD_PATH = "/api/v1/devices/uploads"


def _token(state: Any) -> str:
    from .device_channel_auth import channel_token  # noqa: PLC0415

    return channel_token(state, False)


def _base(state: Any) -> str:
    from . import device_state  # noqa: PLC0415

    return str(device_state.load_device(state).get("base_url") or "").rstrip("/")


def unpack(data: bytes, dest: Path) -> tuple[int, list[str]]:
    dest = Path(dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    written, refused = 0, []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            pure = PurePosixPath(member.name)
            target = (dest / pure).resolve()
            if pure.is_absolute() or ".." in pure.parts or not target.is_relative_to(dest) or not (
                    member.isfile() or member.isdir()):
                refused.append(member.name)
                continue
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            target.write_bytes(source.read() if source is not None else b"")
            target.chmod(0o644)
            written += 1
    return written, refused


def fetch(state: Any, item: dict[str, Any], dest: Path, *, http: Any = None) -> tuple[Path | None, str]:
    url = str(item.get("url") or "")
    if not url.startswith("/api/v1/devices/archives/"):
        return None, "not an archive the platform offered"
    client = http or httpx.Client(timeout=TIMEOUT)
    try:
        response = client.get(_base(state) + url, headers={"Authorization": f"Bearer {_token(state)}"})
    except httpx.HTTPError as error:
        return None, f"the archive could not be fetched ({type(error).__name__})"
    if response.status_code != 200:
        return None, f"the archive could not be fetched (HTTP {response.status_code})"
    if hashlib.sha256(response.content).hexdigest() != str(item.get("sha256") or ""):
        return None, "the archive does not match its sha256; nothing was unpacked"
    _written, refused = unpack(response.content, dest)
    return Path(dest), ("" if not refused else f"left out unsafe members: {', '.join(refused[:10])}")


def upload(state: Any, data: bytes, *, name: str, http: Any = None) -> dict[str, Any] | str:
    client = http or httpx.Client(timeout=TIMEOUT)
    try:
        response = client.post(_base(state) + UPLOAD_PATH, params={"name": name[:120]}, content=data,
                               headers={"Authorization": f"Bearer {_token(state)}"})
    except httpx.HTTPError as error:
        return f"the upload failed ({type(error).__name__})"
    if response.status_code != 200:
        return f"the upload was refused (HTTP {response.status_code})"
    return dict(response.json())


__all__ = ["fetch", "unpack", "upload"]
