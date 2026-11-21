// The status line of Knowledge → Search: how many sources the workspace has and whether they are current, in one
// short line ("6 sources · up to date"). It counts sources, not documents or indexing jobs: the sources are what
// Knowledge learns from, and the Sources page holds their details. The indexing backlog appears only while there is
// one ("Indexing: 187 waiting").

import type { SourceListing } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeTypes";
import type { SourceConnector } from "../../admin/components/workspaceKnowledge/connectorTypes";
import { instanceSchedulerState } from "../../admin/components/workspaceKnowledge/connectorFreshness";
import { sourceState } from "../../admin/components/workspaceKnowledge/sources/sourceState";
import type { SourceStateWord } from "../../admin/components/workspaceKnowledge/sources/sourceState";
import { hasNoDocuments, indexingJobs, plural } from "./knowledgeEntryModel";

// The connectors listing as the server returns it (the same one the Sources page reads).
export type ConnectorListing = { connectors: SourceConnector[]; instance_scheduler_enabled?: boolean };

export type StatusInput = {
  listing: SourceListing | null;
  sourcesFailed: boolean;
  connectors: ConnectorListing | null;
  connectorsFailed: boolean;
};

// `muted` is a passing state (indexing, syncing); `attention` needs someone to act.
export type StatusTone = "plain" | "muted" | "attention";
export type StatusItem = { key: "sources" | "state"; label: string; text: string; tone: StatusTone };

/** "6 sources": the sources of the Sources page, so the number links there. */
export function sourcesStatus(input: StatusInput): StatusItem {
  const item = { key: "sources" as const, label: "Sources" };
  if (input.connectorsFailed) return { ...item, text: "Sources unavailable", tone: "attention" };
  if (!input.connectors) return { ...item, text: "Loading sources…", tone: "muted" };
  const count = input.connectors.connectors.length;
  if (count) return { ...item, text: plural(count, "source", "sources"), tone: "plain" };
  // Uploaded documents are not a source of the Sources page.
  const uploads = input.listing && !hasNoDocuments(input.listing);
  return { ...item, text: uploads ? "No connected sources" : "No sources yet", tone: "plain" };
}

/** One word for all sources and the indexing behind them; null while loading or when there is nothing to state. */
export function freshnessStatus(input: StatusInput, now = Date.now()): StatusItem | null {
  const settled = (input.listing || input.sourcesFailed) && (input.connectors || input.connectorsFailed);
  if (!settled) return null;
  const item = { key: "state" as const, label: "State" };
  const connectors = input.connectors?.connectors ?? [];
  const schedulingOn = instanceSchedulerState(input.connectors) !== "off";
  const words = connectors.map((connector) => sourceState(connector, false, schedulingOn, now).word);
  const count = (word: SourceStateWord) => words.filter((entry) => entry === word).length;
  const jobs = input.listing && !input.sourcesFailed ? indexingJobs(input.listing) : null;
  // The first that applies wins: what needs someone to act, then what is still under way.
  const attention = count("Needs attention");
  if (attention) return { ...item, text: `${attention} ${attention === 1 ? "needs" : "need"} attention`, tone: "attention" };
  if (jobs?.failed) return { ...item, text: `Indexing: ${jobs.failed} failed`, tone: "attention" };
  const stale = count("Out of date");
  if (stale) return { ...item, text: `${stale} out of date`, tone: "attention" };
  if (jobs?.waiting) return { ...item, text: `Indexing: ${jobs.waiting} waiting`, tone: "muted" };
  if (count("Syncing")) return { ...item, text: "syncing", tone: "muted" };
  const never = count("Never synced");
  if (never) return { ...item, text: `${never} never synced`, tone: "muted" };
  if (!words.length) return null;
  if (words.every((word) => word === "Paused")) return { ...item, text: "paused", tone: "muted" };
  // "Up to date" only while schedules keep every source current, as on the Sources page; else "synced".
  return { ...item, text: count("Synced") ? "synced" : "up to date", tone: "plain" };
}

export function statusItems(input: StatusInput, now = Date.now()): StatusItem[] {
  const state = freshnessStatus(input, now);
  return [sourcesStatus(input), ...(state ? [state] : [])];
}
