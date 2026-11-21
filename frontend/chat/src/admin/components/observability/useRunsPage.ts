import { useCallback, useEffect, useState } from "react";

import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import { readErrorMessage } from "./obFormat";
import { RUN_OUTCOMES, runsQuery, type RunPage, type RunRow } from "./runsModel";

// The runs page's filters, the loaded page (a search waits 250 ms) and the opened run.
export function useRunsPage(readJson: ReadJsonFn) {
  const [windowHours, setWindowHours] = useState(24);
  const [workspaceId, setWorkspaceId] = useState("");
  const [source, setSource] = useState("");
  // ``?outcome=`` in the address (e.g. needs_clarification) preselects the filter.
  const [outcome, setOutcome] = useState(() => {
    const value = typeof window === "undefined" ? "" : new URLSearchParams(window.location.search).get("outcome") ?? "";
    return (RUN_OUTCOMES as string[]).includes(value) ? value : "";
  });
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<RunPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [openRun, setOpenRun] = useState<RunRow | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await readJson<RunPage>(runsQuery({ windowHours, workspaceId, source, outcome, query, page })));
      setError(null);
    } catch (loadError) {
      setError(readErrorMessage(loadError, "Runs could not be loaded."));
    } finally {
      setLoading(false);
    }
  }, [readJson, windowHours, workspaceId, source, outcome, query, page]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), query ? 250 : 0);
    return () => window.clearTimeout(timer);
  }, [load, query]);

  return {
    windowHours, setWindowHours, workspaceId, setWorkspaceId, source, setSource, outcome, setOutcome, query, setQuery,
    page, setPage, data, error, loading, openRun, setOpenRun, load,
  };
}

export type RunsPageState = ReturnType<typeof useRunsPage>;
