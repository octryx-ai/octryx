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

// Knowledge › Sources: one state per source, read from the connectors listing only. Pure, so the rules
// are tested without React.
//
// A launcher snapshot completes passes without a sync run, so `last_run` is empty while the cursor counts
// passes (never "Never run" next to "3 full passes"). The last sync is therefore the latest of the last
// run, the last clean pass and the last closed pass, and "Never synced" means none of them exists.

// "Up to date" only while a schedule keeps the source current; a source synced by hand or by upload says when it
// last synced instead ("Synced 7 Oct · manual"), because nothing keeps it current. Such a source is "Out of
// date" once its last sync is older than STALE_AFTER_DAYS ("Synced" next to a month-old manual sync).
export type SourceStateWord =
  | "Syncing" | "Up to date" | "Synced" | "Out of date" | "Needs attention" | "Paused" | "Never synced";
export type SourceTone = "active" | "warning" | "inactive" | "danger";

export type SourceState = {
  word: SourceStateWord;
  tone: SourceTone;
  // One sentence, only when the state needs one (attention, or a pass that continues on the next sync).
  reason: string | null;
  lastSyncAt: number | null;
};

const sentence = (text: string) => {
  const trimmed = text.trim().replace(/[.:;,\s]+$/, "");
  return trimmed ? `${trimmed.charAt(0).toUpperCase()}${trimmed.slice(1)}.` : "";
};

/** When the source last synced anything: the latest run, clean pass or closed pass; null when it never did. */
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

/** Whether something keeps the source current: its own schedule, while the instance runs schedules. */
export function keptCurrent(connector: SourceConnector, schedulingOn = true): boolean {
  return schedulingOn && !isLocalSnapshot(connector) && scheduleOf(connector).enabled;
}

/** Why an out-of-date source is not synced: its age, and what (not) keeps it current. */
function staleReason(connector: SourceConnector, at: number, schedulingOn: boolean, now: number): string {
  const age = syncAgeText(at, now);
  if (isLocalSnapshot(connector)) return `${age}. Only a new upload by the launcher updates it.`;
  if (!schedulingOn && scheduleOf(connector).enabled) {
    return `${age}. Automatic sync is off on this instance, so only Sync now syncs it.`;
  }
  return `${age}. It has no schedule, so only Sync now syncs it.`;
}

/** The one state of a source, with its reason when it needs one. `running` is a run started from this page. */
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

/** "Confluence", "Jira", "Code", …: the same words Search uses for where a hit comes from. */
export function sourceOriginLabel(kind: string): string {
  return originLabel(kind);
}

/** The source's name: a repository's label ("server-config (config, b26f235)") or its key. */
export function sourceName(connector: SourceConnector): string {
  const label = (connector as { display_label?: unknown }).display_label;
  return typeof label === "string" && label.trim() ? label.trim() : connector.connector_key;
}

/** What it reads, on one line: spaces, projects, knowledge bases and tables, a repository or a cluster. */
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

/** "242 pages", "1 file"; null when the connector carries no `served_items` count. */
export function servedItemsText(connector: SourceConnector): string | null {
  const served = connector.served_items;
  if (typeof served !== "number" || !Number.isFinite(served) || served < 0) return null;
  return `${served} ${itemNoun(connector.kind, served !== 1)}`;
}

/** A name's words (split at spaces only): the table wraps between them, never at a hyphen inside one. */
export function nameWords(name: string): string[] {
  return name.split(/\s+/).filter(Boolean);
}

/** "720 articles and records" as ["720 articles", "and", "records"]: the count always stays with its noun. */
export function countParts(text: string): string[] {
  const words = nameWords(text);
  return words.length > 2 ? [words.slice(0, 2).join(" "), ...words.slice(2)] : [words.join(" ")];
}

/** How it syncs: by launcher upload, by hand, or every n minutes. */
export function sourceCadence(connector: SourceConnector): string {
  if (isLocalSnapshot(connector)) return "uploaded by the launcher";
  const schedule = scheduleOf(connector);
  return schedule.enabled ? `every ${intervalText(schedule.interval_minutes)}` : "manual";
}
