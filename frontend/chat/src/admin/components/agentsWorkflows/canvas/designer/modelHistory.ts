// Designer model history: undo and redo as a list of models, with quick same-key changes as one step.
import { HISTORY_LIMIT, type DesignModel } from "./modelCore";

export type History = {
  past: DesignModel[];
  present: DesignModel;
  future: DesignModel[];
  // Changes with the same key in quick succession (typing a name) are one step.
  key?: string;
  at?: number;
};

export const startHistory = (present: DesignModel): History => ({ past: [], present, future: [] });
const COALESCE_MS = 1200;

export function commit(history: History, next: DesignModel, key?: string, now: number = Date.now()): History {
  if (next === history.present) return history;
  if (key && history.key === key && history.at !== undefined && now - history.at < COALESCE_MS) {
    return { ...history, present: next, future: [], at: now };
  }
  return { past: [...history.past, history.present].slice(-HISTORY_LIMIT), present: next, future: [], key, at: now };
}

export function undo(history: History): History {
  if (!history.past.length) return history;
  return { past: history.past.slice(0, -1), present: history.past[history.past.length - 1], future: [history.present, ...history.future] };
}

export function redo(history: History): History {
  if (!history.future.length) return history;
  return { past: [...history.past, history.present], present: history.future[0], future: history.future.slice(1) };
}
