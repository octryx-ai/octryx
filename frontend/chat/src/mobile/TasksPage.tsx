// The open tasks (the app must show which tasks are open
// and where they are kept on the platform): every unfinished Work item of the person's Workspaces, by state, mine or
// all, searchable. Tapping one opens it as a case (ticket, run, steering).

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { loadCaseRuns, loadTasks } from "./mobileApi";
import { type MobileError } from "./mobileSession";
import { nextOffset, readCases, readTaskCounts, stateLabel, type Case, type TaskCounts } from "./mobileTasksModel";
import { Icon } from "./icons";
import { TabHeader } from "./PageHeader";
import { useRefreshEvent } from "./pullToRefresh";
import { TaskRow } from "./TaskRow";

// Tickets count as yours through your linked accounts (never by name); without one, "Mine" stays empty.
export function LinkHint() {
  return (
    <span className="m-link-hint">
      {" "}
      Tickets assigned to you in Jira show here once your Jira account is linked (in the web: Profile, Linked
      accounts).
    </span>
  );
}

function useTasks(workspace: string, initialMine: boolean) {
  const [mine, setMine] = useState(initialMine);
  const [state, setState] = useState("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [items, setItems] = useState<Case[]>([]);
  const [counts, setCounts] = useState<TaskCounts>({ total: 0, states: [] });
  const [more, setMore] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const runs = useRef<unknown>(null);
  const asked = useRef(0);

  const load = useCallback(
    async (offset = 0) => {
      const ticket = ++asked.current;
      setLoading(true);
      try {
        if (offset === 0 || runs.current === null) runs.current = await loadCaseRuns(workspace).catch(() => null);
        const page = await loadTasks({ mine, state, q: search, offset, project: workspace });
        if (ticket !== asked.current) return; // a newer filter answered first
        const rows = readCases(page, runs.current, { keepOrder: true });
        setItems((current) => (offset === 0 ? rows : [...current, ...rows]));
        setCounts(readTaskCounts(page));
        setMore(nextOffset(page));
        setError("");
      } catch (reason) {
        if (ticket !== asked.current) return;
        setError((reason as MobileError).status === 403 ? "Your role does not show Work items." : "The tasks could not be loaded.");
      } finally {
        if (ticket === asked.current) setLoading(false);
      }
    },
    [mine, state, search, workspace],
  );

  useEffect(() => {
    void load(0);
  }, [load]);
  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(query), 350);
    return () => window.clearTimeout(timer);
  }, [query]);
  useRefreshEvent(useCallback(() => load(0), [load]));
  // Another Workspace has other states: the state filter starts over.
  useEffect(() => setState(""), [workspace]);
  return { mine, setMine, state, setState, query, setQuery, search, items, counts, more, loading, error, load };
}

function TaskFilters({ tasks }: { tasks: ReturnType<typeof useTasks> }) {
  const { mine, setMine, state, setState, query, setQuery, counts } = tasks;
  return (
    <div className="m-task-filters">
      <div className="m-segment" role="group" aria-label="Whose Work items">
        <button type="button" aria-pressed={!mine} onClick={() => setMine(false)}>
          All
        </button>
        <button type="button" aria-pressed={mine} onClick={() => setMine(true)}>
          Assigned to me
        </button>
      </div>
      <label className="m-search">
        <Icon name="search" size={18} />
        <input
          type="search"
          aria-label="Search Work items"
          placeholder="Search key or title"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      <div className="m-chips" role="group" aria-label="State">
        <button type="button" className="m-chip" aria-pressed={!state} onClick={() => setState("")}>
          All <span className="m-chip-count">{counts.total}</span>
        </button>
        {counts.states.map((item) => (
          <button
            key={item.state}
            type="button"
            className="m-chip"
            aria-pressed={state === item.state}
            onClick={() => setState(state === item.state ? "" : item.state)}
          >
            {item.label} <span className="m-chip-count">{item.count}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export function TasksPage({
  workspaces,
  workspace,
  switcher,
  initialMine = false,
  onOpen,
}: {
  initialMine?: boolean;
  workspaces: Record<string, string>;
  // The phone's Workspace choice; "" for all of the person's Workspaces.
  workspace: string;
  switcher: ReactNode;
  onOpen: (item: Case) => void;
}) {
  const tasks = useTasks(workspace, initialMine);
  const { mine, state, search, items, counts, more, loading, error, load } = tasks;

  const shown = state ? (counts.states.find((item) => item.state === state)?.count ?? items.length) : counts.total;

  return (
    <>
      <TabHeader
        title="Work items"
        switcher={switcher}
        subtitle={loading && !items.length ? undefined : `${shown} open${mine ? " · assigned to you" : ""}`}
      />
      <main className="m-body">
        <TaskFilters tasks={tasks} />
        {error && (
          <p className="m-banner m-banner-problem" role="alert">
            {error}
          </p>
        )}
        {!error && !loading && items.length === 0 && (
          <p className="m-empty">
            {mine ? "Nothing open is assigned to you" : "Nothing open"}
            {state ? ` in ${stateLabel(state)}` : ""}
            {search ? ` for “${search}”` : ""}.
            {mine && !state && !search && <LinkHint />}
          </p>
        )}
        <ul className="m-rows m-group">
          {items.map((item) => (
            <TaskRow key={item.id} item={item} workspace={workspaces[item.projectId] ?? ""} onOpen={onOpen} />
          ))}
        </ul>
        {loading && <p className="m-empty">Loading…</p>}
        {!loading && more !== null && (
          <button type="button" className="m-more" onClick={() => void load(more)}>
            Show more
          </button>
        )}
      </main>
    </>
  );
}
