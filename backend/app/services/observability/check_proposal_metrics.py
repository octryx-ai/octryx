"""From Correction to Check, measured at the event (never from a database query):

- ``octryx_check_proposals_total{workspace,kind,state}``: every proposal the platform made (``proposed``) and every
  decision on one (``approved``, ``rejected``, ``edited``);
- ``octryx_check_proposal_proofs_total{workspace,outcome}``: every proof offered to a device (``offered``) and how it
  ended (``proven``, ``failed``, ``unavailable``: no code state, no device, or the device gave no result).

Imports only ``metric_types`` (``agent_metrics`` imports this module early).
"""

from __future__ import annotations

from .metric_types import Counter, _Metric

PROPOSALS = Counter("octryx_check_proposals_total", "Check proposals made (proposed) and decided (approved, rejected,"
                    " edited) by Workspace and check kind", ("workspace", "kind", "state"))

PROOFS = Counter("octryx_check_proposal_proofs_total", "Proofs of proposed checks offered to a device (offered) and"
                 " how they ended (proven, failed, unavailable) by Workspace", ("workspace", "outcome"))

METRICS: tuple[_Metric, ...] = (PROPOSALS, PROOFS)


def count(workspace_id: str, kind: str, state: str) -> None:
    PROPOSALS.inc(workspace=workspace_id, kind=kind or "unknown", state=state)


def count_proof(workspace_id: str, outcome: str) -> None:
    PROOFS.inc(workspace=workspace_id, outcome=outcome)


def reset() -> None:
    """Tests: start empty."""
    for metric in METRICS:
        metric.series.clear()
