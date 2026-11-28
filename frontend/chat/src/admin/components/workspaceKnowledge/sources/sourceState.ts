import { apiTimeOf } from "../apiTime";
import { completedWithFailures, itemNoun, runResultText, syncAgeText, syncIsStale } from "../connectorFreshness";
import { intervalText } from "../connectorDisplay";
import { reasonText } from "../connectorReasons";
import { scheduleOf } from "../connectorConfig";
import type { SourceConnector } from "../connectorTypes";
import { gitScopeSummary, isLocalSnapshot } from "../gitRepositoryScope";
import { storedPageTrees } from "../confluencePageTree";
import { originLabel } from "../search/searchFacets";
import { REST_KIND } from "../rest/restSourceForm";
import { aclStateOf } from "../rest/restSourceSample";

// A launcher snapshot completes passes without a sync run, so the last sync is the latest of run, clean pass and closed pass.

// Only a schedule keeps a source current; one synced by hand or upload says when it last synced instead.
export type SourceStateWord =
  | "Syncing" | "Up to date" | "Synced" | "Out of date" | "Needs attention" | "Paused" | "Never synced";
export type SourceTone = "active" | "warning" | "inactive" | "danger";

export type SourceState = {
  word: SourceStateWord;
  tone: SourceTone;
  reason: string | null;
  lastSyncAt: number | null;
};

const sentence = (text: string) => {
  const trimmed = text.trim().replace(/[.:;,\s]+$/, "");
  return trimmed ? `${trimmed.charAt(0).toUpperCase()}${trimmed.slice(1)}.` : "";
};

export function lastSyncAt(connector: SourceConnector): number | null {
  const run = connector.last_run;
  const times = [
    apiTimeOf(run?.finished_at ?? run?.started_at ?? null),
    apiTimeOf(connector.cursor?.last_completed_at ?? null),
    apiTimeOf(connector.cursor?.last_pass_closed_at ?? null),
  ].filter((time): time is number => time !== null);
  return times.length ? Math.max(...times) : null;
}

function attentionReason(connector: SourceConnector): string | null {
  const run = connector.last_run;
  if (run && (run.state === "failed" || run.state === "needs_configuration")) {
    return sentence(reasonText(run.reason)) || runResultText(run, connector.kind);
  }
  if (run && completedWithFailures(run)) return runResultText(run, connector.kind);
  if (connector.release_sync?.state === "needs_configuration") return "Jira releases need a product for each project.";
  // A restricted REST source "runs" but indexes nothing while the Workspace does not enforce source permissions.
  if (connector.kind === REST_KIND && aclStateOf(connector.acl)?.restricted_items_withheld) {
    return "Restricted items are held back: this Workspace does not enforce source permissions.";
  }
  return null;
}

export function keptCurrent(connector: SourceConnector, schedulingOn = true): boolean {
  return schedulingOn && !isLocalSnapshot(connector) && scheduleOf(connector).enabled;
}

function staleReason(connector: SourceConnector, at: number, schedulingOn: boolean, now: number): string {
  const age = syncAgeText(at, now);
  if (isLocalSnapshot(connector)) return `${age}. Only a new upload by the launcher updates it.`;
  if (!schedulingOn && scheduleOf(connector).enabled) {
    return `${age}. Automatic sync is off on this instance, so only Sync now syncs it.`;
  }
  return `${age}. It has no schedule, so only Sync now syncs it.`;
}

export function sourceState(connector: SourceConnector, running = false, schedulingOn = true, now = Date.now()): SourceState {
  const at = lastSyncAt(connector);
  if (connector.running || running) return { word: "Syncing", tone: "inactive", reason: null, lastSyncAt: at };
  if (connector.state === "paused") return { word: "Paused", tone: "inactive", reason: null, lastSyncAt: at };
  const attention = attentionReason(connector);
  if (attention) return { word: "Needs attention", tone: "warning", reason: attention, lastSyncAt: at };
  const passes = connector.cursor?.completed_passes ?? 0;
  if (at === null && !passes && !connector.cursor?.pass_started_at) {
    return { word: "Never synced", tone: "inactive", reason: null, lastSyncAt: null };
  }
  if (connector.cursor?.pass_started_at) {
    return { word: "Syncing", tone: "inactive", reason: "Continues with the next sync.", lastSyncAt: at };
  }
  if (!keptCurrent(connector, schedulingOn)) {
    return at !== null && syncIsStale(at, now)
      ? { word: "Out of date", tone: "warning", reason: staleReason(connector, at, schedulingOn, now), lastSyncAt: at }
      : { word: "Synced", tone: "active", reason: null, lastSyncAt: at };
  }
  return { word: "Up to date", tone: "active", reason: null, lastSyncAt: at };
}

export function sourceOriginLabel(kind: string): string {
  return originLabel(kind);
}

export function sourceName(connector: SourceConnector): string {
  const label = (connector as { display_label?: unknown }).display_label;
  return typeof label === "string" && label.trim() ? label.trim() : connector.connector_key;
}

export function sourceContainer(connector: SourceConnector): string {
  const scope = connector.scope ?? {};
  if (connector.kind === "git_repository") {
    const summary = gitScopeSummary(scope);
    return [summary.repository, summary.ref ? `at ${summary.ref}` : ""].filter(Boolean).join(" ");
  }
  if (connector.kind === REST_KIND) {
    return [scope.definition, scope.operation].filter((part) => typeof part === "string" && part).join(" · ")
      + (typeof scope.role === "string" && scope.role ? ` as ${scope.role}` : "");
  }
  if (connector.kind === "kubernetes") {
    const namespaces = scope.namespaces ?? [];
    return `Cluster ${scope.cluster ?? "?"}${namespaces.length ? ` · ${namespaces.join(", ")}` : ""}`;
  }
  if (connector.kind === "servicenow") {
    const bases = scope.knowledge_bases ?? [];
    return [bases.length ? `${bases.length} knowledge base${bases.length === 1 ? "" : "s"}` : "",
      (scope.tables ?? []).join(", ")].filter(Boolean).join(" · ");
  }
  const trees = connector.kind === "confluence" ? storedPageTrees(scope).length : 0;
  const keys = scope.spaces ?? scope.project_keys ?? [];
  return [keys.join(", "), trees ? `${trees} page tree${trees === 1 ? "" : "s"}` : "", scope.jql ? "JQL filter" : ""]
    .filter(Boolean).join(" · ");
}

export function servedItemsText(connector: SourceConnector): string | null {
  const served = connector.served_items;
  if (typeof served !== "number" || !Number.isFinite(served) || served < 0) return null;
  return `${served} ${itemNoun(connector.kind, served !== 1)}`;
}

// Split at spaces only, so the table never wraps at a hyphen inside a name.
export function nameWords(name: string): string[] {
  return name.split(/\s+/).filter(Boolean);
}

export function countParts(text: string): string[] {
  const words = nameWords(text);
  return words.length > 2 ? [words.slice(0, 2).join(" "), ...words.slice(2)] : [words.join(" ")];
}

export function sourceCadence(connector: SourceConnector): string {
  if (isLocalSnapshot(connector)) return "uploaded by the launcher";
  const schedule = scheduleOf(connector);
  return schedule.enabled ? `every ${intervalText(schedule.interval_minutes)}` : "manual";
}
