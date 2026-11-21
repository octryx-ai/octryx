import { Badge, Segmented, WorkspaceSelect, type ProjectOption } from "./obUi";
import { formatDuration, formatMoney, formatTime } from "./obFormat";
import { outcomeLabel, outcomeTone, RUN_OUTCOMES, RUN_SOURCES, RUN_WINDOWS, toolsLabel, type RunPage, type RunRow } from "./runsModel";
import type { RunsPageState } from "./useRunsPage";

function CostCell({ row }: { row: RunRow }) {
  if (row.cost_state === "unpriced") return <Badge tone="attention">! unpriced</Badge>;
  if (row.cost_state === "not_billed") return <span className="ob-muted">seat</span>;
  return <>{formatMoney(row.cost)}</>;
}

// Search, Workspace, source, outcome and window; every filter change goes back to page 1.
export function RunsToolbar({ state, projects }: { state: RunsPageState; projects: ProjectOption[] }) {
  const { query, setQuery, workspaceId, setWorkspaceId, source, setSource, outcome, setOutcome, windowHours, setWindowHours, setPage, load, loading } = state;
  const filter = (apply: () => void) => {
    apply();
    setPage(1);
  };
  return (
    <div className="ob-toolbar">
      <input
        className="admin-users__toolbar-input"
        type="search"
        aria-label="Search runs"
        placeholder="Search user, agent, workflow"
        value={query}
        onChange={(event) => filter(() => setQuery(event.target.value))}
      />
      <WorkspaceSelect projects={projects} value={workspaceId} onChange={(value) => filter(() => setWorkspaceId(value))} />
      <select
        className="admin-users__toolbar-select"
        aria-label="Source"
        value={source}
        onChange={(event) => filter(() => setSource(event.target.value))}
      >
        <option value="">All sources</option>
        {RUN_SOURCES.map((item) => (
          <option key={item} value={item}>{item}</option>
        ))}
      </select>
      <select
        className="admin-users__toolbar-select"
        aria-label="Outcome"
        value={outcome}
        onChange={(event) => filter(() => setOutcome(event.target.value))}
      >
        <option value="">All outcomes</option>
        {RUN_OUTCOMES.map((item) => (
          <option key={item} value={item}>{outcomeLabel(item)}</option>
        ))}
      </select>
      <Segmented label="Window" options={RUN_WINDOWS} value={windowHours} onChange={(value) => filter(() => setWindowHours(value))} />
      <button type="button" className="admin-panel__action-btn" onClick={() => void load()} disabled={loading}>
        Refresh
      </button>
    </div>
  );
}

// One row per run; a row (click or Enter) opens the run drawer.
export function RunsTable({ data, onOpen }: { data: RunPage | null; onOpen: (row: RunRow) => void }) {
  return (
    <table className="admin-panel__table ob-cards">
      <thead>
        <tr>
          <th>Time</th>
          <th>Workspace · user</th>
          <th>Agent / workflow</th>
          <th>Source</th>
          <th>Outcome</th>
          <th className="ob-num">Tools</th>
          <th className="ob-num">Duration</th>
          <th className="ob-num">Cost</th>
        </tr>
      </thead>
      <tbody>
        {(data?.items ?? []).map((row) => (
          <tr
            key={row.run_key}
            className="ob-row-button"
            tabIndex={0}
            onClick={() => onOpen(row)}
            onKeyDown={(event) => {
              if (event.key === "Enter") onOpen(row);
            }}
          >
            <td data-label="Time">{formatTime(row.time)}</td>
            <td data-label="Workspace · user">
              <div className="ob-name">{row.workspace_name ?? "No Workspace"}</div>
              <div className="ob-sub">{row.user_name ?? "–"}</div>
            </td>
            <td data-label="Agent / workflow">{row.agent_label ?? "Chat"}</td>
            <td data-label="Source"><Badge tone="neutral">{row.source}</Badge></td>
            <td data-label="Outcome"><Badge tone={outcomeTone(row.outcome)}>{outcomeLabel(row.outcome)}</Badge></td>
            <td data-label="Tools" className="ob-num">{toolsLabel(row)}</td>
            <td data-label="Duration" className="ob-num">{formatDuration(row.duration_ms)}</td>
            <td data-label="Cost" className="ob-num"><CostCell row={row} /></td>
          </tr>
        ))}
        {data && !data.items.length ? (
          <tr>
            <td colSpan={8} className="admin-panel__cell--muted">No runs match these filters in the window.</td>
          </tr>
        ) : null}
      </tbody>
    </table>
  );
}
