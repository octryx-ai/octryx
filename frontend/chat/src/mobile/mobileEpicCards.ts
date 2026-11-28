// The phone's Epic summary card: one line and a mini lane bar per Epic, from the platform's progress endpoint.

import { barSegments, readEpicProgress, type EpicBarSegment } from "../chat/work/epicViewModel";
import type { Case } from "./mobileTasksModel";

export const MAX_EPIC_CARDS = 3;

export type EpicCard = { item: Case; line: string; segments: EpicBarSegment[] };

export function epicsShown(items: Case[], max = MAX_EPIC_CARDS): Case[] {
  return items.filter((item) => String(item.issueType || "").trim().toLowerCase() === "epic").slice(0, max);
}

export function readEpicCard(item: Case, raw: unknown): EpicCard {
  const { epic, summary } = readEpicProgress(raw);
  const parts = [
    epic.title || item.title,
    `${summary.done}/${summary.total} done`,
    `${summary.in_progress} in progress`,
    `${summary.in_review} in review`,
    `${summary.open} open`,
  ];
  if (summary.needsYou) parts.push(`${summary.needsYou} ${summary.needsYou === 1 ? "needs" : "need"} you`);
  return { item, line: parts.join(" · "), segments: barSegments(summary) };
}
