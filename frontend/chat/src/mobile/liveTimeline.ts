// Kept-open steps of a live session (per session, in session storage) and its timeline of messages and steps.

import type { LiveMessage } from "./mobileLiveSessions";
import type { ProgressBlock } from "./mobileLiveProgress";

// Which groups and steps are open, per session, kept while the page reloads its data (and across visits when the
// browser allows storage; without it, everything still works and simply starts closed).
const OPEN_KEY = "octryx.live.open.";
export function loadOpen(peer: string): Set<string> {
  try {
    const raw = window.sessionStorage.getItem(OPEN_KEY + peer);
    return new Set(raw ? (JSON.parse(raw) as string[]).slice(-200) : []);
  } catch {
    return new Set();
  }
}
export function saveOpen(peer: string, keys: Set<string>) {
  try {
    window.sessionStorage.setItem(OPEN_KEY + peer, JSON.stringify([...keys].slice(-200)));
  } catch {
    // no storage: the state lives as long as the page
  }
}

export const timeOf = (at: string) => {
  const value = Date.parse(at);
  return Number.isNaN(value) ? 0 : value;
};

export type LiveTimelineEntry =
  | { type: "message"; message: LiveMessage; at: number }
  | { type: "block"; block: ProgressBlock; at: number };

// Messages and steps in the order they happened (a step without a time stays after the one before it).
export function buildLiveTimeline(shownBlocks: ProgressBlock[], messages: LiveMessage[]): LiveTimelineEntry[] {
  const timeline: LiveTimelineEntry[] = [];
  let lastStepAt = 0;
  for (const block of shownBlocks) {
    lastStepAt = timeOf(block.at) || lastStepAt;
    timeline.push({ type: "block", block, at: lastStepAt });
  }
  for (const message of messages)
    timeline.push({ type: "message", message, at: timeOf(message.createdAt) });
  timeline.sort((a, b) => a.at - b.at);
  return timeline;
}
