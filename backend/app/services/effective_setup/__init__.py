"""Effective setup (Agents & workflows → Overview): what an octryx-claude session gets, part by part, from the
functions its MCP surface and hooks use (``external_setup.py``)."""

from .external_setup import RUNTIME_OCTRYX_CLAUDE, external_effective_setup

RUNTIMES = (RUNTIME_OCTRYX_CLAUDE,)

__all__ = ["RUNTIMES", "RUNTIME_OCTRYX_CLAUDE", "external_effective_setup"]
