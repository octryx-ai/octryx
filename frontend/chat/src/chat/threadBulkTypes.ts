// Types of the thread bulk-action hook: its inputs, the confirm dialog and the undo toast.
import type { ThreadBulkResult } from "./threadBulkActions";
import type { ThreadBulkAction, ThreadSelection } from "./threadSelection";

type ReadJsonFn = <T>(input: string, init?: RequestInit) => Promise<T>;

type LoadStateFn = (
  search?: string,
  options?: { preserveTrace?: boolean; silent?: boolean },
) => Promise<void>;

export type ThreadBulkDialog = {
  action: Exclude<ThreadBulkAction, "restore">;
  /** What the dialog acts on: the bulk selection, or one chat from its row menu. */
  selection: ThreadSelection;
  /** Unloaded chats covered by scopes (the "not loaded yet" note). */
  notLoaded: number;
  preview: ThreadBulkResult | null;
  error: string | null;
  running: boolean;
};

export type ThreadBulkToast = {
  text: string;
  undoIds: string[];
  secondsLeft: number;
};

export type ThreadBulkArgs = {
  readJson: ReadJsonFn;
  loadState: LoadStateFn;
  canDeleteThreads: boolean;
  threadSearchQuery: string;
  selectedSessionId: string | null;
  newThreadSearch: string;
  forgetThreads?: (ids: string[]) => void;
};
