"""Redacted, bounded session digest for ``/sessions/finalize``.

Reuses the platform's existing session-ingest code instead of a second redactor:
``backend/scripts/ingest_claude_session.build_digest`` distills the Claude Code
transcript (user asks + assistant text) and
``backend/scripts/mcp_session_ingest_common.cap_digest`` redacts secrets and caps the
size. Both live in the same repository as this kit; the installed package carries
copies of the two files in ``_platform_scripts`` (the platform adds them when it builds the wheel).
"""

from __future__ import annotations

import sys
from pathlib import Path

_CHECKOUT_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "backend" / "scripts"
_PACKAGED_SCRIPTS_DIR = Path(__file__).resolve().parent / "_platform_scripts"
_SCRIPTS_DIR = _PACKAGED_SCRIPTS_DIR if _PACKAGED_SCRIPTS_DIR.is_dir() else _CHECKOUT_SCRIPTS_DIR


def _load():
    scripts = str(_SCRIPTS_DIR)
    if scripts not in sys.path:
        sys.path.append(scripts)
    import ingest_claude_session  # noqa: PLC0415 - lives outside this package
    import mcp_session_ingest_common  # noqa: PLC0415

    return ingest_claude_session.build_digest, mcp_session_ingest_common.cap_digest


def transcript_inside(transcript_path: str, claude_config_dir: Path) -> Path | None:
    """The transcript path when it is a regular file inside the octryx config dir."""
    if not transcript_path:
        return None
    try:
        resolved = Path(transcript_path).expanduser().resolve()
        root = claude_config_dir.resolve()
    except OSError:
        return None
    if not resolved.is_file() or resolved.suffix != ".jsonl":
        return None
    if root not in resolved.parents:
        return None
    return resolved


def build_redacted_digest(transcript: Path) -> str:
    build_digest, cap_digest = _load()
    return cap_digest(build_digest(str(transcript)))
