"""Teams call recordings on disk: owner-only, in the configured data directory, removed after use.

A downloaded recording is spooled while the call turn is processed so an operator can inspect a
live turn. It lives under the data directory (the parent of ``artifact_store_dir``, like the other
platform data), in a directory only the service user can open (0700), as a file only the service
user can read (0600) under a random name. The file is deleted when processing ends, whatever the
outcome. A spool failure never stops the call turn; it is logged as a closed code.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ...config import get_settings
from ..error_facts import error_text

logger = logging.getLogger(__name__)

RECORDINGS_DIRNAME = "teams-call-recordings"
_DIR_MODE = 0o700
_FILE_MODE = 0o600


def recordings_dir() -> Path:
    return Path(get_settings().artifact_store_dir).expanduser().resolve().parent / RECORDINGS_DIRNAME


def _write_owner_only(directory: Path, audio_bytes: bytes) -> Path:
    directory.mkdir(mode=_DIR_MODE, parents=True, exist_ok=True)
    os.chmod(directory, _DIR_MODE)
    path = directory / f"{uuid.uuid4().hex}.wav"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(audio_bytes)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


@contextmanager
def spooled_recording(audio_bytes: bytes, *, directory: Path | None = None) -> Iterator[Path | None]:
    """Yield the spooled file (``None`` when spooling failed) and delete it afterwards."""
    path: Path | None = None
    try:
        path = _write_owner_only(directory or recordings_dir(), audio_bytes)
        logger.debug("Call recording spooled: bytes=%d", len(audio_bytes))
    except OSError as exc:
        logger.warning("Call recording not spooled: %s", error_text("call_recording_spool_failed", exc))
    try:
        yield path
    finally:
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(
                    "Call recording spool not removed: %s", error_text("call_recording_cleanup_failed", exc)
                )
