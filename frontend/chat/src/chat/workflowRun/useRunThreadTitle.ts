import { useSyncExternalStore } from "react";

import { runThreadTitleOf, subscribeRunThreadTitles } from "./runBarModel";

/** The open run thread's title (" Login fix · Waiting for you"), or null for a chat without a run. */
export function useRunThreadTitle(sessionId: string | null | undefined): string | null {
  return useSyncExternalStore(subscribeRunThreadTitles, () => runThreadTitleOf(sessionId), () => null);
}
