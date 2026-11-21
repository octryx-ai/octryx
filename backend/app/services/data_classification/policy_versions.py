"""The governed classification policy: draft → review → publish under the approval rule.

The classification policy (matrix overrides and the level for new Workspaces) changes only through a version:

- an admin saves a **draft** (one open draft at a time); the draft is validated with the same rules as the live
  matrix (``policy_matrix.normalize_policy_levels``). The per-level model list is not edited here: it keeps the
  published value (it is derived from each model's clearance in Runtime → Model catalog);
- **submit** runs the saved policy test cases against the draft (``candidate.candidate_policy``) and opens a review
  (an ``approvals`` row, so the review also shows in Observability → Approvals); a failing case blocks;
- **approve** decides the review and publishes in one step when the approval rule allows it
  (``governance.four_eyes.decide_four_eyes``: another admin under four-eyes, the author too under single admin),
  re-running the test cases; publishing writes the content into the live stores the decision points read
  (``set_classification_policy`` and ``set_instance_default``) and retires the previous version;
- **reject** sends the version back to draft with the reviewer's comment; **rollback** opens a draft from an older
  version.

Nothing here commits; the routes do.

The implementation is split by step (``policy_version_content``, ``policy_version_store``, ``policy_version_drafts``,
``policy_version_publish``); this module keeps every name importable from here.
"""

from __future__ import annotations

__all__ = []
