"""Where the two content enforcement entry points, enforcement_call (platform) and enforcement_inbound (gateway),
differ on purpose: one named rule each, held by tests/content_security/test_surface_rules.py."""

from __future__ import annotations

from dataclasses import dataclass

from .handling import SURFACE_GATEWAY, SURFACE_PLATFORM

INJECTION_ANYWHERE = "anywhere"
#: The older turns and results a client re-sends were admitted before: refusing them again ends the conversation.
INJECTION_NEWEST_TURN = "newest_turn"
CEDAR_READS_AS_FOUND = "as_found"
#: What the probe withheld (an unfinished part) is out of the messages before Cedar reads them.
CEDAR_READS_PROBED = "probed"
SHADOW_WOULD_REMEDY = "would_remedy"
SHADOW_WOULD_DENY = "would_deny"


@dataclass(frozen=True, slots=True)
class SurfaceRules:
    surface: str
    injection: str
    cedar_reads: str
    shadow: str  # what a shadow-mode denial records
    client_tool_check: bool  # Workspace set only, in enforce mode; an unanswerable engine refuses any found kind


PLATFORM = SurfaceRules(SURFACE_PLATFORM, INJECTION_ANYWHERE, CEDAR_READS_PROBED, SHADOW_WOULD_REMEDY,
                        client_tool_check=False)
GATEWAY = SurfaceRules(SURFACE_GATEWAY, INJECTION_NEWEST_TURN, CEDAR_READS_AS_FOUND, SHADOW_WOULD_DENY,
                       client_tool_check=True)
# Undecided: an uncompilable policy set denies a clean platform tool result; the gateway's client tool check passes it.


__all__ = [
    "CEDAR_READS_AS_FOUND",
    "CEDAR_READS_PROBED",
    "GATEWAY",
    "INJECTION_ANYWHERE",
    "INJECTION_NEWEST_TURN",
    "PLATFORM",
    "SHADOW_WOULD_DENY",
    "SHADOW_WOULD_REMEDY",
    "SurfaceRules",
]
