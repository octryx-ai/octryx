import { StatusLabel } from "../../layout/StatusLabel";
import { taskState } from "./taskListModel";
import type { RunTaskItem } from "./workflowRunTypes";

// The work item's tasks with their status (decision card and work item detail): ✓ for done/verified, a label where
// something is going on, the review's finding under a task with requested changes, the proof test on the right.
export function TaskList({ items }: { items: RunTaskItem[] }) {
  return (
    <ol className="decision-card__tasks" data-testid="task-list">
      {items.map((item) => {
        const state = taskState(item, items);
        return (
          <li className={`decision-card__task decision-card__task--${state.status}`} key={item.id}
            data-status={state.status}>
            <span className="decision-card__task-id">{item.id}</span>
            <span className="decision-card__item-text">{item.text}</span>
            {state.mark === "label" ? <StatusLabel label={state.label} tone={state.tone} /> : null}
            {state.mark === "check" ? (
              <span className="decision-card__task-done" title={state.label} aria-label={state.label}>
                {state.status === "verified" ? "✓✓" : "✓"}
              </span>
            ) : null}
            {state.mark === "none" ? <span aria-hidden="true" /> : null}
            <code className="decision-card__place" title={item.proof}>{item.proof.split("/").pop()}</code>
            {state.status === "changes" && item.note ? (
              <p className="decision-card__task-note">{item.note}</p>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
