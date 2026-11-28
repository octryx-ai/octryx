// Counts sources, not documents or indexing jobs: the sources are what Knowledge learns from.

import type { SourceListing } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeTypes";
import type { SourceConnector } from "../../admin/components/workspaceKnowledge/connectorTypes";
import { instanceSchedulerState } from "../../admin/components/workspaceKnowledge/connectorFreshness";
import { sourceState } from "../../admin/components/workspaceKnowledge/sources/sourceState";
import type { SourceStateWord } from "../../admin/components/workspaceKnowledge/sources/sourceState";
import { hasNoDocuments, indexingJobs, plural } from "./knowledgeEntryModel";

export type ConnectorListing = { connectors: SourceConnector[]; instance_scheduler_enabled?: boolean };

export type StatusInput = {
  listing: SourceListing | null;
  sourcesFailed: boolean;
  connectors: ConnectorListing | null;
  connectorsFailed: boolean;
};

export type StatusTone = "plain" | "muted" | "attention";
export type StatusItem = { key: "sources" | "state"; label: string; text: string; tone: StatusTone };

export function sourcesStatus(input: StatusInput): StatusItem {
  const item = { key: "sources" as const, label: "Sources" };
  if (input.connectorsFailed) return { ...item, text: "Sources unavailable", tone: "attention" };
  if (!input.connectors) return { ...item, text: "Loading sources…", tone: "muted" };
  const count = input.connectors.connectors.length;
  if (count) return { ...item, text: plural(count, "source", "sources"), tone: "plain" };
  const uploads = input.listing && !hasNoDocuments(input.listing);
  return { ...item, text: uploads ? "No connected sources" : "No sources yet", tone: "plain" };
}

export function freshnessStatus(input: StatusInput, now = Date.now()): StatusItem | null {
  const settled = (input.listing || input.sourcesFailed) && (input.connectors || input.connectorsFailed);
  if (!settled) return null;
  const item = { key: "state" as const, label: "State" };
  const connectors = input.connectors?.connectors ?? [];
  const schedulingOn = instanceSchedulerState(input.connectors) !== "off";
  const words = connectors.map((connector) => sourceState(connector, false, schedulingOn, now).word);
  const count = (word: SourceStateWord) => words.filter((entry) => entry === word).length;
  const jobs = input.listing && !input.sourcesFailed ? indexingJobs(input.listing) : null;
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
  // "Up to date" only while schedules keep every source current, as on the Sources page.
  return { ...item, text: count("Synced") ? "synced" : "up to date", tone: "plain" };
}

export function statusItems(input: StatusInput, now = Date.now()): StatusItem[] {
  const state = freshnessStatus(input, now);
  return [sourcesStatus(input), ...(state ? [state] : [])];
}
