import { useCallback, useLayoutEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { readJson } from "../../utils/adminPanelHelpers";
import type { PanelScheduler } from "../taskTypes";

const SCHEDULERS_URL = "/admin/chat/api/panel/schedulers";
const systemNow = () => new Date();

export type SchedulerStatusCheck = {
  checking: boolean;
  error: string | null;
  /** When the user last checked; null means the status is from when the list was loaded. */
  checkedAt: Date | null;
};

/**
 * Apply a status reply that was requested when the list was `snapshot` to the list as it is
 * now (`current`). Local writes (save, pause/resume, create, delete) replace row objects or
 * remove rows, so a row that is still the snapshot's object is untouched since the check began:
 *
 * - untouched rows take the fetched version, or disappear when the server no longer lists them;
 * - rows replaced by a local write keep that newer local result;
 * - rows deleted locally stay deleted (only `current` rows are kept or updated);
 * - rows unknown to the snapshot are added only when the list did not change at all in flight,
 *   so a row created and deleted during the check cannot reappear.
 */
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

/**
 * Explicit "Check worker status": one list request per click, never polling.
 *
 * Deliberately not the panel's `loadTab`: that swaps the whole tab for a loading or error
 * view, which would unmount an open create/edit form. Here only list rows change, through
 * `mergeStatusCheck`, so a slow reply cannot undo a save or pause made meanwhile or bring back
 * a deleted row; form fields live in separate state and stay as they are. A failed check keeps
 * the last known rows and says so; an older check reply never overwrites a newer one.
 */
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
  // The committed list, read when a check starts (its snapshot).
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
