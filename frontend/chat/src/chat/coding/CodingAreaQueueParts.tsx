// Parts of the Coding page: its one primary action, the session filter tabs with the search, and the empty queue.
import { SegmentedTabs } from "../../layout/SegmentedTabs";
import { CodingQueueEmptyState } from "./CodingQueueEmptyState";
import { sessionInQueue, type CodingQueueKey } from "./codingQueuePresenter";
import type { CodingSessionSummary } from "./codingTypes";

// The Sessions filter tabs: All · Running · Review ready · Blocked · Completed over one list.
const SESSION_TABS: Array<{ queue: CodingQueueKey; label: string }> = [
  { queue: "sessions", label: "All" },
  { queue: "running", label: "Running" },
  { queue: "review", label: "Review ready" },
  { queue: "blocked", label: "Blocked" },
  { queue: "completed", label: "Completed" },
];

type StartActionProps = {
  rulesPage: boolean;
  canAddRule: boolean;
  activeQueue: CodingQueueKey | null;
  startBlocked: string | null;
  onAddRule: () => void;
  onStart: () => void;
};

export function CodingAreaStartAction({ rulesPage, canAddRule, activeQueue, startBlocked, onAddRule, onStart }: StartActionProps) {
  return rulesPage ? (
    // The page's one action is adding a rule, for those who may; anyone else reads the rules.
    canAddRule ? (
      <button type="button" className="work-area__button work-area__button--primary" data-testid="coding-rules-add"
        onClick={onAddRule}>Add rule</button>
    ) : null
  ) : !activeQueue ? null : startBlocked ? (
    // A primary action that cannot reach its goal is not bright; the reason stands next to it.
    <span className="page-header__blocked">
      <button type="button" className="work-area__button work-area__button--primary" disabled
        aria-describedby="coding-start-blocked">Start coding session</button>
      <span id="coding-start-blocked" className="page-header__hint">{startBlocked}</span>
    </span>
  ) : (
    <button type="button" className="work-area__button work-area__button--primary" onClick={onStart}>
      Start coding session
    </button>
  );
}

type FiltersProps = {
  sessions: CodingSessionSummary[];
  sessionQueue: CodingQueueKey;
  setSessionQueue: (queue: CodingQueueKey) => void;
  showSearch: boolean;
  search: string;
  setSearch: (search: string) => void;
};

export function CodingSessionFilters({ sessions, sessionQueue, setSessionQueue, showSearch, search, setSearch }: FiltersProps) {
  return (
    <>
      {/* The shared segments: the admin tab classes this used have no styles here. The wrapper
          keeps the segments their own width in the body's grid. */}
      <div className="coding-session-views">
        <SegmentedTabs label="Session filter" idPrefix="coding-sessions" value={sessionQueue} testId="coding-session-tabs"
          tabs={SESSION_TABS.map((tab) => ({ key: tab.queue, label: tab.label,
            count: sessions.filter((session) => sessionInQueue(session, tab.queue)).length }))}
          onChange={(key) => setSessionQueue(key as CodingQueueKey)} />
      </div>
      {showSearch ? (
        <div className="coding-area__filters">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search sessions, repos, branches..."
            aria-label="Search Coding Sessions"
          />
        </div>
      ) : null}
    </>
  );
}

type EmptyProps = {
  queue: CodingQueueKey;
  queueCount: number;
  workItemCount: number;
  search: string;
  sessions: CodingSessionSummary[];
  onStart: () => void;
  onClearSearch: () => void;
  onOpenQueue: (queue: CodingQueueKey) => void;
};

export function CodingAreaEmptyQueue({ sessions, ...props }: EmptyProps) {
  return (
    <CodingQueueEmptyState
      {...props}
      unavailableReviewCount={sessions.filter((session) => session.review.status === "unavailable").length}
    />
  );
}
