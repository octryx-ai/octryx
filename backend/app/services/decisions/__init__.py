"""The decision timeline: "was it allowed".

Every gate writes its non-allow outcomes to ``policy_decision_log`` (through the policy engine's buffer) and
counts its allows per hour; the approval lifecycle and the shipped content policies
(``content_security.model_call``) are decision records too. Observability → Decisions reads them (``timeline``).
"""

# The approval lifecycle listener registers itself on import.
from . import approvals as _approvals  # noqa: E402,F401
