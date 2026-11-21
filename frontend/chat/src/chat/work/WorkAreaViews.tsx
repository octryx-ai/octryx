import { useState } from "react";
import "./workItemsLean.css";
import { isServiceNowItem } from "./incident/workSourceModel";

import type { WorkItem } from "./workItemTypes";
import type { WorkNavKey } from "./workTypes";
import type { WorkWorkflowDefinition } from "./workSyncWorkflowTypes";
import { workEmptyStateFor, type WorkEmptyAction } from "./workEmptyStates";
import { badgeTone } from "./workUtils";
import { workBoardColumns, workStateKey } from "./workBoardColumns";
import { assigneeLabel } from "./workPeople";
import { firstException, workItemExceptions, type WorkException } from "./workItemExceptions";
import { TimeText } from "../../admin/utils/TimeText";
import { StatusLabel } from "../../layout/StatusLabel";
import { DataTable, type DataTableColumn } from "../../layout/DataTable";
import { ourStateLabel, ourStateTone } from "./workItemState";

type WorkItemOpenHandler = (item: WorkItem) => void;

type WorkEmptyProps = { nav?: WorkNavKey; hasItems?: boolean; onEmptyAction?: (action: WorkEmptyAction) => void };

export function WorkBoard({
  items,
  hasIntakes,
  onOpenItem,
  workflows = [],
  nav = "board",
  hasItems = false,
  onEmptyAction,
}: {
  items: WorkItem[];
  hasIntakes: boolean;
  onOpenItem: WorkItemOpenHandler;
  // The columns are the workflow states; every item is in exactly one column.
  workflows?: WorkWorkflowDefinition[];
} & WorkEmptyProps) {
  // L-f: empty states are hidden (and named) so the populated columns fit; one click shows every state.
  const [showEmpty, setShowEmpty] = useState(false);
  // Done is folded by default, its count stays visible; one click shows its cards.
  const [showDone, setShowDone] = useState(false);
  if (items.length === 0) {
    return <WorkEmptyState hasIntakes={hasIntakes} nav={nav} hasItems={hasItems} onAction={onEmptyAction} />;
  }
  const all = workBoardColumns(items, workflows);
  const empty = all.filter((column) => column.items.length === 0);
  const columns = showEmpty ? all : all.filter((column) => column.items.length > 0);
  return (
    <>
      {empty.length ? (
        <div data-testid="board-empty-states"
          style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "var(--ds-space-2)", margin: "0 0 var(--ds-space-2)",
            color: "var(--muted)", fontSize: "var(--ds-text-xs)" }}>
          <span>
            {showEmpty
              ? `Showing all ${all.length} columns.`
              : `${empty.length} empty ${empty.length === 1 ? "column" : "columns"} hidden.`}
          </span>
          <button type="button" className="work-area__button" aria-pressed={showEmpty} onClick={() => setShowEmpty((value) => !value)}>
            {showEmpty ? "Hide empty columns" : "Show all columns"}
          </button>
        </div>
      ) : null}
    {/* One grid column per state (the stylesheet's default is six); the board scrolls sideways. */}
    <div className="work-board" style={{ gridTemplateColumns: `repeat(${columns.length}, minmax(13rem, 1fr))` }}>
      {columns.map((column) => {
        const stateItems = column.items;
        const folded = column.key === "done" && !showDone && stateItems.length > 0;
        return (
          <section key={column.key} className="work-board__column" data-state={column.key} data-folded={folded || undefined}>
            <header title={column.outsideVocabulary ? "A state outside the workflow states" : undefined}>
              <span>{column.label}</span>
              <strong>{stateItems.length}</strong>
            </header>
            <div className="work-board__cards">
              {folded ? (
                <button type="button" className="work-area__button" data-testid="board-done-toggle" onClick={() => setShowDone(true)}>
                  {`Show ${stateItems.length} done`}
                </button>
              ) : stateItems.map((item) => (
                <WorkCard key={item.id} item={item} onOpenItem={onOpenItem} />
              ))}
              {column.key === "done" && showDone && stateItems.length > 0 ? (
                <button type="button" className="work-area__button" data-testid="board-done-toggle" onClick={() => setShowDone(false)}>
                  Fold done
                </button>
              ) : null}
            </div>
          </section>
        );
      })}
    </div>
    </>
  );
}

function WorkCard({ item, onOpenItem }: { item: WorkItem; onOpenItem: WorkItemOpenHandler }) {
  // Key, title and the assignee; badges only for exceptions. The card's column already names our state,
  // so the card does not repeat it. The source's own status (a localized Jira uses its own word for "To do")
  // stays on the detail's source tab.
  return (
    <button type="button" className="work-card" onClick={() => onOpenItem(item)}>
      <span className="work-card__topline">
        <span className="work-card__key">{item.source_key}</span>
        <span>
          {isServiceNowItem(item) ? <span className="work-badge work-badge--neutral" data-testid="work-source-badge">ServiceNow</span> : null}
          <ExceptionBadges exceptions={workItemExceptions(item)} />
        </span>
      </span>
      <span className="work-card__title">{item.title}</span>
      <span className="work-card__meta">
        <span>{assigneeLabel(item)}</span>
      </span>
    </button>
  );
}

/** The exception badges of an item (workItemExceptions); nothing when the item is ordinary. */
export function ExceptionBadges({ exceptions }: { exceptions: WorkException[] }) {
  if (!exceptions.length) return null;
  return (
    <>
      {exceptions.map((exception) => (
        <span key={exception.key} className={`work-badge work-badge--${exception.tone}`} data-testid="work-exception">
          {exception.label}
        </span>
      ))}
    </>
  );
}

export const WORK_TABLE_PAGE_SIZE = 50;

/** When the item last changed (at the source, else here), as a sortable number; 0 when unknown. */
export function workItemUpdatedAt(item: WorkItem): number {
  const value = Date.parse(item.last_source_updated_at || item.updated_at || "");
  return Number.isFinite(value) ? value : 0;
}

/** The table's rows: newest first; Done items left out unless asked for. */
export function workTableRows(items: WorkItem[], showDone: boolean): { rows: WorkItem[]; doneHidden: number } {
  const done = (item: WorkItem) => workStateKey(item.work_state) === "done";
  const kept = showDone ? items : items.filter((item) => !done(item));
  const rows = [...kept].sort((left, right) => workItemUpdatedAt(right) - workItemUpdatedAt(left));
  return { rows, doneHidden: items.length - kept.length };
}

export function WorkTable({
  items,
  hasIntakes,
  onOpenItem,
  workflows = [],
  nav = "board",
  hasItems = false,
  onEmptyAction,
  selectedId = null,
  showDoneDefault = false,
}: {
  items: WorkItem[];
  hasIntakes: boolean;
  onOpenItem: WorkItemOpenHandler;
  workflows?: WorkWorkflowDefinition[];
  // The item whose side panel is open.
  selectedId?: string | null;
  // Show Done items from the start (a state filter already chose them).
  showDoneDefault?: boolean;
} & WorkEmptyProps) {
  // The table lists the newest first, leaves Done out until "Show done", shows 50 rows per page and a row click
  // (or Enter) opens the side panel.
  const [showDone, setShowDone] = useState(showDoneDefault);
  const [page, setPage] = useState(0);
  if (items.length === 0) {
    return <WorkEmptyState hasIntakes={hasIntakes} nav={nav} hasItems={hasItems} onAction={onEmptyAction} />;
  }
  const { rows, doneHidden } = workTableRows(items, showDone);
  const doneCount = items.filter((item) => workStateKey(item.work_state) === "done").length;
  const pages = Math.max(1, Math.ceil(rows.length / WORK_TABLE_PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const first = current * WORK_TABLE_PAGE_SIZE;
  const shown = rows.slice(first, first + WORK_TABLE_PAGE_SIZE);
  const toggleDone = () => { setShowDone((value) => !value); setPage(0); };
  const columns: DataTableColumn<WorkItem>[] = [
    { key: "issue", header: "Issue", grow: true, render: (item) => (
      <span className="work-table__issue">
        <strong>{item.source_key}</strong>
        <span>{item.title}</span>
      </span>
    ) },
    { key: "state", header: "State", nowrap: true, render: (item) => <StatusLabel label={ourStateLabel(item, workflows)} tone={ourStateTone(item)} /> },
    { key: "assignee", header: "Assignee", nowrap: true, render: (item) => assigneeLabel(item) },
    { key: "attention", header: "Needs attention", nowrap: true, render: (item) => {
      const exception = firstException(item);
      return exception ? <ExceptionBadges exceptions={[exception]} /> : null;
    } },
    { key: "updated", header: "Updated", nowrap: true, render: (item) => (
      <span className="work-table__time"><TimeText value={item.last_source_updated_at || item.updated_at} fallback="Never" /></span>
    ) },
  ];
  return (
    <div className="work-table-view" data-testid="work-table">
      {doneCount > 0 ? (
        <div className="work-table__bar" data-testid="work-table-done">
          <span>{showDone ? `Done items shown (${doneCount}).` : `${doneHidden} done ${doneHidden === 1 ? "item" : "items"} hidden.`}</span>
          <button type="button" className="work-area__button" aria-pressed={showDone} onClick={toggleDone}>
            {showDone ? "Hide done" : "Show done"}
          </button>
        </div>
      ) : null}
      <DataTable label="Work items" columns={columns} rows={shown} rowKey={(item) => item.id} onOpen={onOpenItem}
        selectedKey={selectedId} testId="work-table-rows"
        empty={{ text: "Every item here is done." }} />
      {pages > 1 ? (
        <nav className="work-table__pager" aria-label="Work item pages" data-testid="work-table-pager">
          <span>{`${first + 1}–${first + shown.length} of ${rows.length}`}</span>
          <button type="button" className="work-area__button" disabled={current === 0} onClick={() => setPage(current - 1)}>Previous</button>
          <button type="button" className="work-area__button" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>Next</button>
        </nav>
      ) : null}
    </div>
  );
}

function WorkEmptyState({
  hasIntakes,
  nav,
  hasItems,
  onAction,
}: {
  hasIntakes: boolean;
  nav: WorkNavKey;
  hasItems: boolean;
  onAction?: (action: WorkEmptyAction) => void;
}) {
  const content = workEmptyStateFor(nav, hasIntakes, hasItems);
  return (
    <div className="work-empty">
      <div className="work-empty__eyebrow">{content.eyebrow}</div>
      <h2>{content.title}</h2>
      <p>{content.body}</p>
      {onAction && content.actions.length ? (
        <div className="work-empty__actions">
          {content.actions.map((entry, index) => (
            <button key={entry.action} type="button"
              className={`work-area__button${index === 0 ? " work-area__button--primary" : ""}`}
              onClick={() => onAction(entry.action)}>
              {entry.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function Badge({ value, labelPrefix }: { value: string; labelPrefix?: string }) {
  return (
    <span className={`work-badge work-badge--${badgeTone(value)}`}>
      {labelPrefix ? `${labelPrefix}: ` : ""}
      {value.replaceAll("_", " ")}
    </span>
  );
}

export function WorkNavIcon({ navKey }: { navKey: WorkNavKey }) {
  const paths: Record<WorkNavKey, string[]> = {
    runs: ["M5 4l10 6-10 6z"],
    epics: ["M10 3l7 4-7 4-7-4z", "M3 11l7 4 7-4", "M3 14l7 4 7-4"],
    board: ["M4 4h5v12H4z", "M11 4h5v5h-5z", "M11 11h5v5h-5z"],
    changePlans: ["M5 4h7l3 3v9H5z", "M11 4v4h4", "M7 12h6"],
    intake: ["M10 3v9", "M6 8l4 4 4-4", "M4 14v2h12v-2"],
    writeback: ["M10 17V8", "M6 12l4-4 4 4", "M4 4h12"],
  };
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      {paths[navKey].map((path) => (
        <path key={path} d={path} />
      ))}
    </svg>
  );
}
