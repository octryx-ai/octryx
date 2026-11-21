// Runs: the workflow runs of the chosen Workspace (Work › Runs' rows), what waits for the person first, and starting
// a new one. Tapping a run opens its view (steps, Parallel work, the decision it waits for).

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { StatusLabel } from "../layout/StatusLabel";
import { Icon } from "./icons";
import { loadRuns } from "./mobileApi";
import { type MobileError } from "./mobileSession";
import { runLineText } from "./engineSeatModel";
import { shortTime } from "./mobileUsageModel";
import { defaultRunFilter, readRunRows, runCounts, runMatches, RUN_FILTERS, type RunFilter, type RunListRow } from "./mobileRuns";
import { TabHeader } from "./PageHeader";
import { useRefreshEvent } from "./pullToRefresh";

const POLL_MS = 15000;

const EMPTY: Record<RunFilter, string> = {
  needs: "No run waits for you.",
  active: "No run is going on.",
  finished: "No finished run yet.",
  all: "No runs in this Workspace yet.",
};

export function RunsPage({
  workspace,
  switcher,
  onOpen,
  onStart,
  onOperations,
}: {
  workspace: string;
  switcher: ReactNode;
  onOpen: (row: RunListRow) => void;
  onStart: () => void;
  // Operations: what runs where right now, what is stuck (all of the person's scope, not only this list).
  onOperations?: () => void;
}) {
  const [rows, setRows] = useState<RunListRow[] | null>(null);
  const [filter, setFilter] = useState<RunFilter | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const next = readRunRows(await loadRuns(workspace));
      setRows(next);
      setFilter((current) => current ?? defaultRunFilter(next));
      setError("");
    } catch (reason) {
      setError((reason as MobileError).status === 403 ? "Your role does not show workflow runs." : "The runs could not be loaded.");
    }
  }, [workspace]);
  useRefreshEvent(load);
  useEffect(() => {
    setRows(null);
    setFilter(null);
    void load();
    const timer = window.setInterval(() => !document.hidden && void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const counts = useMemo(() => runCounts(rows ?? []), [rows]);
  const active = filter ?? "needs";
  const shown = (rows ?? []).filter((row) => runMatches(row, active));

  return (
    <>
      <TabHeader
        title="Runs"
        switcher={switcher}
        actions={
          <button type="button" className="m-pill-button" onClick={onStart}>
            <Icon name="plus" size={18} />
            Start run
          </button>
        }
      />
      <main className="m-body">
        {onOperations && (
          <ul className="m-rows m-group">
            <li>
              <button type="button" className="m-row m-row-icon" onClick={onOperations} data-testid="m-runs-operations">
                <span className="m-row-glyph" aria-hidden="true">
                  <Icon name="pulse" size={20} />
                </span>
                <span className="m-row-text">
                  <b>Operations</b>
                  <span>Where each run works, and what is stuck</span>
                </span>
                <Icon name="chevronRight" size={18} className="m-row-chevron" />
              </button>
            </li>
          </ul>
        )}
        <div className="m-segment" role="group" aria-label="Which runs">
          {RUN_FILTERS.map((item) => (
            <button key={item.key} type="button" aria-pressed={active === item.key} onClick={() => setFilter(item.key)}>
              {item.label}
              {counts[item.key] > 0 && <span className="m-segment-count">{counts[item.key]}</span>}
            </button>
          ))}
        </div>
        {error && (
          <p className="m-banner m-banner-problem" role="alert">
            {error}
          </p>
        )}
        {rows === null && !error && <p className="m-empty">Loading…</p>}
        {rows !== null && shown.length === 0 && (
          <div className="m-empty">
            <p>{EMPTY[active]}</p>
            {active === "all" && (
              <button type="button" className="m-secondary" onClick={onStart}>
                Start a run
              </button>
            )}
          </div>
        )}
        <ul className="m-rows m-group">
          {shown.map((row) => (
            <li key={row.id}>
              <button type="button" className="m-row m-row-run" onClick={() => onOpen(row)}>
                <span className="m-row-text">
                  <b>{row.subject}</b>
                  <span>{[row.workflow, row.step].filter(Boolean).join(" · ")}</span>
                  {row.line && <span data-testid="m-run-line">{runLineText(row.line)}</span>}
                  <span className="m-row-status">
                    <StatusLabel label={row.label} tone={row.tone} />
                  </span>
                </span>
                <span className="m-when">{shortTime(row.updatedAt)}</span>
              </button>
            </li>
          ))}
        </ul>
      </main>
    </>
  );
}
