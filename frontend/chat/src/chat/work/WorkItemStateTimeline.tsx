import { useEffect, useState } from "react";

import { loadWorkItemStateEvents } from "./workTransitionApi";
import { formatDateTime } from "./workUtils";
import { jiraEffectText } from "./workTransitionModel";
import { workStateLabel } from "./workBoardColumns";
import type { WorkStateEvent, WorkWorkflowDefinition } from "./workSyncWorkflowTypes";

// The Work Item's audit timeline of state events: every applied transition and every preview (dry
// run), newest first, with what was written to Jira. Reloads when `reloadKey` changes (after an apply).
export function WorkItemStateTimeline({ workItemId, reloadKey = 0, workflows = [] }: {
  workItemId: string;
  reloadKey?: number;
  // L-f: states by their human label.
  workflows?: WorkWorkflowDefinition[];
}) {
  const [events, setEvents] = useState<WorkStateEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Another item (or a reload) never shows the previous item's events while loading.
    setEvents(null);
    setError(null);
    void loadWorkItemStateEvents(workItemId)
      .then((items) => {
        if (!cancelled) setEvents(items);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load the audit timeline");
      });
    return () => {
      cancelled = true;
    };
  }, [workItemId, reloadKey]);

  if (error) return <p className="work-detail__empty">{error}</p>;
  if (!events) return <p className="work-detail__empty">Loading the audit timeline…</p>;
  if (!events.length) return <p className="work-detail__empty">No state change recorded yet.</p>;
  return (
    <ul className="work-detail__object-list" data-testid="state-timeline">
      {events.map((event) => (
        <li key={event.id}>
          <strong>
            {event.from_state ? workStateLabel(event.from_state, workflows) : "—"} → {workStateLabel(event.to_state, workflows)}
          </strong>{" "}
          · {event.dry_run ? "preview (dry run)" : "applied"} · {formatDateTime(event.created_at)}
          {event.reason ? <div>Reason: {event.reason}</div> : null}
          <div>{jiraEffectText(event)}</div>
        </li>
      ))}
    </ul>
  );
}
