import { toolStatusLabel } from "./toolStatusLabel";
import type { ToolEvent } from "../chatThreadTypes";
import { getToolRows, getToolRowTitle } from "./messageBubbleHelpers";

function ToolRowList({
  rows,
  emptyLabel,
  metaFormatter,
}: {
  rows: Record<string, unknown>[];
  emptyLabel: string;
  metaFormatter?: (row: Record<string, unknown>) => string | null;
}) {
  if (!rows.length) {
    return <div className="tool-inline__empty">{emptyLabel}</div>;
  }

  return (
    <div className="tool-inline__row-list">
      {rows.map((row, index) => {
        const meta = metaFormatter ? metaFormatter(row) : null;
        return (
          <div
            key={`${getToolRowTitle(row)}-${index}`}
            className="tool-inline__row-item"
          >
            <div className="tool-inline__row-title">{getToolRowTitle(row)}</div>
            {meta ? <div className="tool-inline__row-meta">{meta}</div> : null}
          </div>
        );
      })}
    </div>
  );
}

export function ConfluenceDeltaInline({
  event,
  result,
}: {
  event: ToolEvent;
  result: Record<string, unknown>;
}) {
  const projectName =
    typeof result.project_name === "string" ? result.project_name : "Project";
  const totalPages =
    typeof result.total_pages === "number" ? result.total_pages : 0;
  const newCount = typeof result.new_count === "number" ? result.new_count : 0;
  const changedCount =
    typeof result.changed_count === "number" ? result.changed_count : 0;
  const unchangedCount =
    typeof result.unchanged_count === "number" ? result.unchanged_count : 0;
  const removedCount =
    typeof result.removed_count === "number" ? result.removed_count : 0;
  const newPages = getToolRows(result.new_pages);
  const changedPages = getToolRows(result.changed_pages);
  const removedPages = getToolRows(result.removed_pages);

  return (
    <section className="tool-inline tool-inline--confluence-delta">
      <div className="tool-inline__header">
        <span className="tool-inline__badge">Confluence delta</span>
        <span
          className={`tool-inline__status tool-inline__status--${event.status}`}
        >
          {toolStatusLabel(event.status)}
        </span>
      </div>
      <div className="tool-inline__title">
        {projectName}
        <span className="tool-inline__exit">{totalPages} visible pages</span>
      </div>
      <div className="tool-inline__stats">
        <div className="tool-inline__stat">
          <span className="tool-inline__stat-value">{newCount}</span>
          <span className="tool-inline__stat-label">new</span>
        </div>
        <div className="tool-inline__stat">
          <span className="tool-inline__stat-value">{changedCount}</span>
          <span className="tool-inline__stat-label">changed</span>
        </div>
        <div className="tool-inline__stat">
          <span className="tool-inline__stat-value">{removedCount}</span>
          <span className="tool-inline__stat-label">removed</span>
        </div>
        <div className="tool-inline__stat">
          <span className="tool-inline__stat-value">{unchangedCount}</span>
          <span className="tool-inline__stat-label">unchanged</span>
        </div>
      </div>
      {newPages.length ? (
        <details className="tool-inline__details">
          <summary className="tool-inline__summary">View new pages</summary>
          <ToolRowList
            rows={newPages}
            emptyLabel="No new pages"
            metaFormatter={(row) => {
              const currentVersion =
                typeof row.current_version === "number"
                  ? row.current_version
                  : null;
              return currentVersion !== null
                ? `Version ${currentVersion}`
                : null;
            }}
          />
        </details>
      ) : null}
      {changedPages.length ? (
        <details className="tool-inline__details">
          <summary className="tool-inline__summary">View changed pages</summary>
          <ToolRowList
            rows={changedPages}
            emptyLabel="No changed pages"
            metaFormatter={(row) => {
              const currentVersion =
                typeof row.current_version === "number"
                  ? row.current_version
                  : null;
              const storedVersion =
                typeof row.stored_version === "number"
                  ? row.stored_version
                  : null;
              if (currentVersion !== null && storedVersion !== null) {
                return `Version ${storedVersion} -> ${currentVersion}`;
              }
              if (currentVersion !== null) {
                return `Version ${currentVersion}`;
              }
              return null;
            }}
          />
        </details>
      ) : null}
      {removedPages.length ? (
        <details className="tool-inline__details">
          <summary className="tool-inline__summary">View removed pages</summary>
          <ToolRowList
            rows={removedPages}
            emptyLabel="No removed pages"
            metaFormatter={(row) => {
              const key = typeof row.key === "string" ? row.key : "";
              return key ? `Knowledge key ${key}` : null;
            }}
          />
        </details>
      ) : null}
    </section>
  );
}

export function ConfluenceSyncInline({
  event,
  result,
}: {
  event: ToolEvent;
  result: Record<string, unknown>;
}) {
  const projectName =
    typeof result.project_name === "string" ? result.project_name : "Project";
  const mode = typeof result.mode === "string" ? result.mode : "incremental";
  const scanned =
    typeof result.pages_scanned === "number" ? result.pages_scanned : 0;
  const changed =
    typeof result.pages_changed === "number" ? result.pages_changed : 0;
  const unchanged =
    typeof result.pages_unchanged === "number" ? result.pages_unchanged : 0;
  const created =
    typeof result.created_count === "number" ? result.created_count : 0;
  const updated =
    typeof result.updated_count === "number" ? result.updated_count : 0;
  const removed =
    typeof result.removed_count === "number" ? result.removed_count : 0;
  const skippedPages = getToolRows(result.skipped_pages);

  return (
    <section className="tool-inline tool-inline--confluence-sync">
      <div className="tool-inline__header">
        <span className="tool-inline__badge">Knowledge sync</span>
        <span
          className={`tool-inline__status tool-inline__status--${event.status}`}
        >
          {toolStatusLabel(event.status)}
        </span>
      </div>
      <div className="tool-inline__title">
        {projectName}
        <span className="tool-inline__exit">{mode}</span>
      </div>
      <div className="tool-inline__stats">
        <div className="tool-inline__stat">
          <span className="tool-inline__stat-value">{scanned}</span>
          <span className="tool-inline__stat-label">scanned</span>
        </div>
        <div className="tool-inline__stat">
          <span className="tool-inline__stat-value">{changed}</span>
          <span className="tool-inline__stat-label">changed</span>
        </div>
        <div className="tool-inline__stat">
          <span className="tool-inline__stat-value">{unchanged}</span>
          <span className="tool-inline__stat-label">unchanged</span>
        </div>
        <div className="tool-inline__stat">
          <span className="tool-inline__stat-value">{removed}</span>
          <span className="tool-inline__stat-label">removed</span>
        </div>
      </div>
      <div className="tool-inline__meta-row">
        <span>{created} created</span>
        <span>{updated} updated</span>
      </div>
      {skippedPages.length ? (
        <details className="tool-inline__details">
          <summary className="tool-inline__summary">View skipped pages</summary>
          <ToolRowList
            rows={skippedPages}
            emptyLabel="No skipped pages"
            metaFormatter={(row) => {
              const error = typeof row.error === "string" ? row.error : "";
              return error || null;
            }}
          />
        </details>
      ) : null}
    </section>
  );
}
