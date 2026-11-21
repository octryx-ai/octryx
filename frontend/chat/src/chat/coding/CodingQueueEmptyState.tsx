import type { WorkItem } from "../work/workItemTypes";
import { codingQueueEmptyState, type CodingQueueKey } from "./codingQueuePresenter";

export function CodingQueueEmptyState({
  queue,
  queueCount,
  workItemCount,
  search,
  unavailableReviewCount = 0,
  onStart,
  onClearSearch,
  onOpenQueue,
}: {
  queue: CodingQueueKey;
  queueCount: number;
  workItemCount: number;
  search: string;
  unavailableReviewCount?: number;
  onStart: () => void;
  onClearSearch: () => void;
  onOpenQueue: (queue: CodingQueueKey) => void;
}) {
  const content = codingQueueEmptyState(queue, { queueCount, workItemCount, search, unavailableReviewCount });
  return (
    <div className="work-empty">
      <div className="work-empty__eyebrow">{content.eyebrow}</div>
      <h2>{content.title}</h2>
      <p>{content.body}</p>
      <div className="coding-area__empty-actions">
        {content.actions.map((action, index) => {
          const className = `work-area__button${index === 0 ? " work-area__button--primary" : ""}`;
          if (action.kind === "link") {
            return (
              <a key={action.label} className={className} href={action.href}>
                {action.label}
              </a>
            );
          }
          const onClick =
            action.kind === "startSession" ? onStart : action.kind === "clearSearch" ? onClearSearch : () => onOpenQueue(action.queue);
          return (
            <button key={action.label} type="button" className={className} onClick={onClick}>
              {action.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function CodingMissingSessionNotice({ workItem, onStart }: { workItem: WorkItem; onStart: () => void }) {
  return (
    <section className="coding-detail" aria-label="Coding Session detail">
      <header className="coding-detail__header">
        <div>
          <div className="work-area__eyebrow">Work Item</div>
          <h2>{workItem.source_key}</h2>
          <p>{workItem.title}</p>
        </div>
        <div className="coding-detail__header-actions">
          <span className="work-badge work-badge--neutral">no coding session</span>
          <a className="work-area__button" href={`/chat?area=work&work_item_id=${encodeURIComponent(workItem.id)}`}>
            Open Work Item
          </a>
          <button type="button" className="work-area__button work-area__button--primary" onClick={onStart}>
            Start coding session
          </button>
        </div>
      </header>
      <div className="work-empty">
        <div className="work-empty__eyebrow">No coding session yet</div>
        <h2>This work item has no coding session yet.</h2>
        <p>
          A coding session starts with a change plan that names the repositories to change. Start a coding session to
          create it. The cockpit does not show a different task in its place.
        </p>
      </div>
    </section>
  );
}
