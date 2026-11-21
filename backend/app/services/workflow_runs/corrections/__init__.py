"""From correction to check: capture and signature store.

Every correction of an agent's work is captured at event time, redacted (no secret, no person's name), normalised into a
signature per Workspace, repository and app, and counted; ``check_proposals`` proposes a check when a signature
reaches the Workspace's threshold (default 2, data). Sources, kind hints, normalisation and redaction are data
(``corrections.json``).
"""

from .sources import change_request, pipeline_red, pr_comment, refused_call, review_fixed
from .store import Correction, capture, get_signature, settings, view

__all__ = ["Correction", "capture", "change_request", "get_signature", "pipeline_red", "pr_comment", "refused_call",
           "review_fixed", "settings", "view"]
