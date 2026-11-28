"""Read-only reconstruction of one approved provider attempt; never a resend or absence certificate."""
from __future__ import annotations

from typing import Any

from ....models import WorkflowRun
from .target import MODE_CREATE


async def reconcile_attempt(client: Any, run: WorkflowRun, intent: Any, body: str) -> dict[str, Any]:
    from .confluence_v2 import STATUS_CURRENT
    from .confluence_v2_errors import KIND_NOT_FOUND, V2Error
    from .publication_checks import _content_match, _version_message
    from .write_intent import markers_in

    ours_marker = (run.id, intent.operation_id)

    def located(page: Any) -> bool:
        return (page.space_id == intent.space_id and page.parent_id == intent.parent_id
                and page.status == STATUS_CURRENT)

    if intent.operation == MODE_CREATE:
        if intent.result_page_id:
            candidate_ids, scanned = [str(intent.result_page_id)], {"direct": intent.result_page_id}
        else:
            scan = await client.scan_direct_children(intent.parent_id)
            if not scan.complete:
                return {"kind": "incomplete", "reason": f"the parent scan is incomplete ({scan.reason}); an "
                                                        "incomplete scan never proves absence",
                        "pages_read": scan.pages_read}
            candidate_ids = [child.id for child in scan.items if child.type == "page"]
            scanned = {"children": len(scan.items), "pages": len(candidate_ids), "pages_read": scan.pages_read}
        ours, others = [], []
        for candidate in candidate_ids:
            try:
                page = await client.get_page(candidate, storage=True)
            except V2Error as error:
                return {"kind": "incomplete", "reason": f"candidate page {candidate} is unreadable ({error.kind}); "
                                                        "an unreadable candidate never proves absence"}
            found = markers_in(page.storage)
            if ours_marker in found:
                ours.append(page)
            elif any(run_id == run.id for run_id, _op in found):
                others.append({"page_id": page.id,
                               "operations": sorted(op for run_id, op in found if run_id == run.id)})
        detail = {"scan": scanned, "other_operations": others}
        if not ours:
            return {"kind": "unverified", "reason": "no page under the pinned parent carries this operation's "
                                                    "marker; zero matches is never proof that nothing was sent",
                    **detail}
        if len(ours) > 1:
            return {"kind": "unverified", "reason": f"{len(ours)} pages carry this operation's marker; none is "
                                                    "adopted", **detail}
        head = ours[0]
        if not located(head):
            return {"kind": "unverified", "reason": f"page {head.id} carries the marker but is not at the pinned "
                                                    "location; it is not adopted", **detail}
        try:
            original = head if head.version == 1 else await client.get_page(head.id, version=1, storage=True)
        except V2Error as error:
            return {"kind": "incomplete", "reason": f"version 1 of page {head.id} is unreadable ({error.kind})"}
        if original.title != intent.title:
            return {"kind": "unverified", "reason": f"page {head.id} was created with another title: a renamed "
                                                    "or redrafted page is not the approved attempt", **detail}
        match = _content_match(original.storage, body)
        if ours_marker not in markers_in(original.storage) or not match:
            return {"kind": "unverified", "reason": f"page {head.id} does not hold the approved body at version 1 "
                                                    "(a redraft or an edit); it is not adopted", **detail}
        return {"kind": "adopt", "page": original, "head": head, "result_kind": "reconciled_adoption",
                "match": match, **detail}
    # update: read exactly the version this write would have produced
    try:
        at = await client.get_page(intent.page_id, version=intent.expected_version, storage=True)
    except V2Error as error:
        if error.kind != KIND_NOT_FOUND:
            return {"kind": "incomplete", "reason": f"version {intent.expected_version} of page {intent.page_id} "
                                                    f"is unreadable ({error.kind})"}
        try:
            head = await client.get_page(intent.page_id, storage=False)
        except V2Error as head_error:
            return {"kind": "incomplete", "reason": f"page {intent.page_id} is unreadable ({head_error.kind})"}
        return {"kind": "unverified", "reason": f"page {intent.page_id} has no version {intent.expected_version} "
                                                f"(it is at {head.version}); only an executor certification "
                                                "makes this intent sendable again", "head_version": head.version}
    try:
        head = await client.get_page(intent.page_id, storage=False)
    except V2Error as error:
        return {"kind": "incomplete", "reason": f"page {intent.page_id} is unreadable ({error.kind})"}
    if not located(head):
        return {"kind": "unverified", "reason": f"page {intent.page_id} is not at the pinned location"}
    match = _content_match(at.storage, body)
    if not match or at.title != intent.title:
        return {"kind": "unverified", "reason": f"version {intent.expected_version} of page {intent.page_id} is "
                                                "not the approved body; it is not adopted"}
    ours = ours_marker in markers_in(at.storage) and at.version_message == _version_message(intent)
    return {"kind": "adopt", "page": at, "head": head, "match": match,
            "result_kind": "reconciled_adoption" if ours else "desired_state_reached"}
