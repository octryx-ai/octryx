# Secure Work

Work Items, their intakes (Jira, ServiceNow, Custom REST), change plans, coding runs, pull request records and the
write-back of Work states to the source tracker.

## Invariants

- A Work Item or related row of a Workspace outside the caller's scope answers the same 404 as a missing one
  (`access.require_work_item_scope`, `related_rows.load_related`).
- A transition whose workflow belongs to another Workspace than the item's is refused, also when the user ACL is
  skipped (`workflow_access.require_workflow_scope`).
- An intake insert that collides with an item of another Workspace is refused (`workspace_immutable.insert_source_item`).
- A review event never keeps a decision record the caller sent, and the reviewer gate counts only that server-written
  record (`review_feedback.py`, `coding/coding_review_evidence.py`).
- A Custom REST write-back that no person decided is only proposed, never sent (`custom_rest/write_back.py`).
- A Jira write-back to an issue outside the connection's project allowlist sends no request (`jira/jira_state_sync.py`).
- A ServiceNow work note is posted only on a confirmed request, never with text the secret scan flags
  (`servicenow/worknote.py`).
- An Epic's progress is derived only from its children's recorded events (work state, latest run, pull request
  record, CI), first matching rule wins, and the derivation writes nothing (`epic_progress/rules.py`).
