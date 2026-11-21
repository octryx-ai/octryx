"""The four-eyes decision on a proposed check.

Pure functions over the proposal dict, the same rule as the prompt catalog: who wrote or changed a proposal does not
approve it. The platform as author counts as nobody, so one permitted person may approve an unedited platform
proposal; an edited one needs a second person. Every refusal says what to do instead.
"""

from __future__ import annotations

from typing import Any

STATE_PROPOSED, STATE_APPROVED, STATE_REJECTED = "proposed", "approved", "rejected"
MAX_REASON = 500


class CheckProposalRefusedError(Exception):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def authors(proposal: dict[str, Any]) -> set[str]:
    """The people who wrote or changed it (the platform author is nobody)."""
    people = {str(edit.get("by")) for edit in proposal.get("edits") or [] if edit.get("by")}
    author = proposal.get("author") or {}
    if author.get("kind") == "person" and author.get("user_id"):
        people.add(str(author["user_id"]))
    return people


def approve_refusal(proposal: dict[str, Any], *, user_id: str, may_approve: bool,
                    accept_unproven: bool) -> CheckProposalRefusedError | None:
    """Why ``user_id`` may not approve ``proposal`` now, or ``None``."""
    if proposal.get("state") != STATE_PROPOSED:
        return CheckProposalRefusedError("not_proposed",
                                         f"This check is {proposal.get('state')}; only a proposed check is approved.")
    if not may_approve:
        return CheckProposalRefusedError("approver_permission_missing",
                       "You may not approve checks in this Workspace; instead ask a person with that permission "
                       "(by default the Workspace owner).", 403)
    if user_id in authors(proposal):
        return CheckProposalRefusedError("four_eyes_required",
                       "You changed this proposal, so a second person approves it; instead ask another approver.", 403)
    if (proposal.get("proof") or {}).get("state") != "proven" and not accept_unproven:
        return CheckProposalRefusedError("proof_missing",
                       "The check is not proven yet (red on the past mistakes, green on clean code); instead wait "
                       "for the proof, or approve it explicitly without proof.")
    return None


def editable_refusal(proposal: dict[str, Any]) -> CheckProposalRefusedError | None:
    if proposal.get("state") != STATE_PROPOSED:
        return CheckProposalRefusedError("not_proposed",
                                         "Only a proposed check is changed; instead switch an approved one off.")
    return None


def instead_refusal(message: dict[str, Any]) -> CheckProposalRefusedError | None:
    """A check's message names the allowed alternative; a bare "not allowed" is a defect (concept, Rules)."""
    if not str((message or {}).get("instead") or "").strip():
        return CheckProposalRefusedError("instead_required",
                                         "The message must say what to do instead; add the allowed alternative.",
                                         422)
    return None


def reason_refusal(reason: Any) -> CheckProposalRefusedError | None:
    text = str(reason or "").strip()
    if not text or len(text) > MAX_REASON:
        return CheckProposalRefusedError("reason_required", f"Say why, in 1 to {MAX_REASON} characters.", 422)
    return None


__all__ = ["MAX_REASON", "CheckProposalRefusedError", "STATE_APPROVED", "STATE_PROPOSED", "STATE_REJECTED",
           "approve_refusal",
           "authors", "editable_refusal", "instead_refusal", "reason_refusal"]
