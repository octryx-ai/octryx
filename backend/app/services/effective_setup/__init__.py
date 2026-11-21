"""Effective setup (Agents & workflows → Overview): what a session actually gets, part by part.

Platform chat is read from a rolled-back dry run of the real run preparation
(``dry_run.py``); octryx-claude from the functions its MCP surface and hooks use
(``external_setup.py``). ``turn_record.py`` compares a recorded turn with the dry run.
"""

from .chat_setup import RUNTIME_CHAT, chat_effective_setup
from .external_setup import RUNTIME_OCTRYX_CLAUDE, external_effective_setup
from .turn_record import compare_prompt_refs, latest_turn_record, session_setup_inputs

RUNTIMES = (RUNTIME_CHAT, RUNTIME_OCTRYX_CLAUDE)

__all__ = [
    "RUNTIMES",
    "RUNTIME_CHAT",
    "RUNTIME_OCTRYX_CLAUDE",
    "chat_effective_setup",
    "compare_prompt_refs",
    "external_effective_setup",
    "latest_turn_record",
    "session_setup_inputs",
]
