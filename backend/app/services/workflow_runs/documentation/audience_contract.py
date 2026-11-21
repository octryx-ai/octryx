"""The audience proof's shared vocabulary: roles, semantics, limits, refusal codes and the proof error.

Server-owned publication, principal and assertion bindings live in ``audience_publication``,
``audience_principals`` and ``audience_query_set``. Queries come only from the newest confirmed publication card.
Accounts, Workspace/source ACLs and Knowledge provenance are rechecked; no access object or credential is fabricated.
"""

from __future__ import annotations

from ....models import WorkflowRun
from ....models.runtime.documentation_publication import (
    RECEIPT_OUTCOME_NEGATIVE,
    RECEIPT_OUTCOME_POSITIVE,
)
from .knowledge_proof import CLASS_AUDIENCE_UNPROVEN
from .page import SETTINGS_KEY

AUDIENCE_KEY = "audience_proof"
AUDIENCE_CONFIG_PATH = f"{SETTINGS_KEY}.{AUDIENCE_KEY}"
PROOF_CONTEXT_KEY = "audience_proof"
PROVENANCE_KEY = "provenance"

ROLE_AUDIENCE = "audience"
ROLE_OUTSIDER = "outsider"
ROLES = (ROLE_AUDIENCE, ROLE_OUTSIDER)
EXPECTED_OUTCOME = {ROLE_AUDIENCE: RECEIPT_OUTCOME_POSITIVE, ROLE_OUTSIDER: RECEIPT_OUTCOME_NEGATIVE}
SEMANTICS_WORKSPACE = "workspace_readers"
SEMANTICS_SOURCE = "source_restricted"
SEMANTICS = (SEMANTICS_WORKSPACE, SEMANTICS_SOURCE)
AUTHOR_ROLES = frozenset({"admin", "owner"})

DEFAULT_TTL_HOURS = 72
MAX_TTL_HOURS = 7 * 24
QUERY_MODE = "lexical"
QUERY_LIMIT = 10
MAX_ASSERTIONS = 40
MAX_QUERY_CHARS = 300
PROBE_WORDS = 8
MAX_LINK_ITEMS = 10
LINKS_HEADING = "links"
# The criteria section is asserted per criterion id; it is not also asserted as one section.
CRITERIA_HEADING = "acceptance criteria and tests"
REFUSAL_WORKSPACE = "workspace_not_accessible"

EVENT_ISSUED = "audience_challenge_issued"
EVENT_CONSUMED = "audience_receipt_consumed"
EVENT_REFUSED = "audience_receipt_refused"

# Fixed refusal codes (the route maps them to a status; the run maps them to a class).
CODE_NEEDS_CONFIGURATION = "needs_configuration"
CODE_NOT_PUBLISHED = "not_published"
CODE_NOT_PROVEN = "provenance_missing"
CODE_BINDING = "binding_mismatch"
CODE_PRINCIPAL = "principal_refused"
CODE_STATE = "state_refused"
CODE_EXPIRED = "expired"
CODE_UNKNOWN = "unknown_challenge"
CODE_UNPROVEN = "assertions_failed"
CODE_CONCURRENT = "concurrent_update"


class AudienceProofError(Exception):
    """A refused challenge, record or consume: a fixed ``code``, its run ``failure_class`` and HTTP ``status``."""

    def __init__(self, code: str, detail: str, *, failure_class: str = CLASS_AUDIENCE_UNPROVEN,
                 status: int = 409) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.failure_class = failure_class
        self.status = status


def role_pass_key(run: WorkflowRun, role: str) -> str:
    """The receipt's pass: the run's current ``<node>#<entry>``, qualified by the principal role."""
    from ..external_step import pass_key

    return f"{pass_key(run)}@{role}"
