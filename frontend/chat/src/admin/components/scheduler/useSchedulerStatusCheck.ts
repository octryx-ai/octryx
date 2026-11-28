import { useCallback, useLayoutEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { readJson } from "../../utils/adminPanelHelpers";
import type { PanelScheduler } from "../taskTypes";

const SCHEDULERS_URL = "/admin/chat/api/panel/schedulers";
const systemNow = () => new Date();

export type SchedulerStatusCheck = {
  checking: boolean;
  error: string | null;
  checkedAt: Date | null;
};

// Local writes replace row objects, so a row that is still the snapshot's object is untouched since the check began.
export function mergeStatusCheck(
  snapshot: PanelScheduler[],
  current: PanelScheduler[],
  fetched: PanelScheduler[],
): PanelScheduler[] {
  if (current === snapshot) return fetched;
  const before = new Map(snapshot.map((row) => [row.id, row]));
  const latest = new Map(fetched.map((row) => [row.id, row]));
  const merged: PanelScheduler[] = [];
  for (const row of current) {
    if (before.get(row.id) !== row) {
      merged.push(row);
    } else if (latest.has(row.id)) {
      merged.push(latest.get(row.id) as PanelScheduler);
    }
  }
  return merged;
}

// Not loadTab: that swaps the whole tab for a loading view and would unmount an open form.
export function useSchedulerStatusCheck(
  schedulers: PanelScheduler[],
  setSchedulers: Dispatch<SetStateAction<PanelScheduler[]>>,
  now: () => Date = systemNow,
) {
  const [state, setState] = useState<SchedulerStatusCheck>({
    checking: false,
    error: null,
    checkedAt: null,
  });
  const latest = useRef(0);
  const rows = useRef(schedulers);
  useLayoutEffect(() => {
    rows.current = schedulers;
  }, [schedulers]);

  const check = useCallback(async () => {
    const request = ++latest.current;
    const snapshot = rows.current;
    setState((previous) => ({ ...previous, checking: true, error: null }));
    try {
      const fetched = await readJson<PanelScheduler[]>(SCHEDULERS_URL);
      if (latest.current !== request) return;
      setSchedulers((current) => mergeStatusCheck(snapshot, current, fetched));
      setState({ checking: false, error: null, checkedAt: now() });
    } catch (error: unknown) {
      if (latest.current !== request) return;
      const message = (error as { message?: unknown } | null)?.message;
      setState((previous) => ({
        ...previous,
        checking: false,
        error:
          typeof message === "string" && message ? message : "Request failed",
      }));
    }
  }, [setSchedulers, now]);

  return { ...state, check };
}
