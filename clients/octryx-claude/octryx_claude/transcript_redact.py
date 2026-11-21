"""The Mac's secret pass over a transcript line before it leaves for the platform (full transcripts).

With the Workspace's ``session_transcripts`` switch on, file contents are the point and they go. Secret values
never do. The rules are the platform's own file, ``backend/scripts/transcript_secrets.py``, loaded the way
:mod:`digest` loads the finalize digest's redactor: from the checkout, or from the copy the platform vendors into the
installed package. The Mac, the platform's store and the platform's reads therefore apply exactly the same rules:
secret-like assignments, known token formats, JSON fields (also escaped), and the whole output of secret commands
and credential-file reads. The session lessons' shapes (:func:`session_lessons.redact`) and the digest's redactor
also run on every string.

Shape-only filters miss e.g. ``STRIPE_KEY=sk_live_…`` and a ``{"password": …}`` inside a string. If the rules file is
missing, the upload fails closed: nothing is sent.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from types import ModuleType
from typing import Any

from .digest import _SCRIPTS_DIR
from .session_lessons import redact as redact_shapes

SECRET_OUTPUT = "[redacted: output of a secret command or credential file]"
_LOADED: dict[str, Any] = {}


def _scripts() -> None:
    scripts = str(_SCRIPTS_DIR)
    if scripts not in sys.path:
        sys.path.append(scripts)


def rules() -> ModuleType:
    """``transcript_secrets`` (required: an ImportError stops the upload, it never sends unredacted lines)."""
    if "rules" not in _LOADED:
        _scripts()
        import transcript_secrets  # noqa: PLC0415 - lives outside this package

        _LOADED["rules"] = transcript_secrets
    return _LOADED["rules"]


def _digest_redactor() -> Callable[[str], str] | None:
    if "digest" not in _LOADED:
        _scripts()
        try:
            import mcp_session_ingest_common  # noqa: PLC0415 - lives outside this package

            _LOADED["digest"] = mcp_session_ingest_common.redact
        except Exception:  # noqa: BLE001 - the shared rules and the lessons' shapes still apply
            _LOADED["digest"] = None
    return _LOADED["digest"]


def redact_text(text: str) -> str:
    text = redact_shapes(rules().redact_text(text))
    digest = _digest_redactor()
    return digest(text) if digest is not None else text


def _strings(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: _strings(item) for key, item in value.items()}
    return value


def secret_source(name: str, tool_input: dict[str, Any]) -> bool:
    return bool(rules().secret_source(name, tool_input))


def redact_line(entry: Any, secret_ids: set[str]) -> Any:
    """One transcript line ready to leave the Mac; ``secret_ids`` collects, across lines, the tool calls whose
    output is replaced as a whole."""
    return _strings(rules().redact_line(entry, secret_ids))


__all__ = ["SECRET_OUTPUT", "redact_line", "redact_text", "rules", "secret_source"]
