// Custom REST source: the dry run's answer as the form shows it, and the status lines with the ACL notice.
import type { Visibility } from "./restSourceForm";
import { RESTRICTED_TEXT, WORKSPACE_TEXT } from "./restSourceRules";
import { restReasonText } from "./restSourceRefusals";
import { record, str } from "./restSourceValues";

// ---- dry run ------------------------------------------------------------------------------------------------------

export type AclState = { visibility: Visibility; acl_enforced: boolean; restricted_items_withheld: boolean; note: string | null };

export type SampleRow = {
  id: string;
  title: string;
  url: string;
  updated: string;
  hidden: boolean;
  // Who finds it after a sync, in words; for a hidden item why it is hidden.
  who: string;
  // What will be ingested: the server's masked excerpt (at most 300 characters, "[redacted]" where a secret was), or
  // why there is none. Both null for a hidden item, which never shows its content.
  excerpt: string | null;
  excerptNote: string | null;
};

export type RestSampleView = {
  rows: SampleRow[];
  listed: number;
  hidden: number;
  skipped: number;
  skippedReasons: string[];
  dropped: number;
  role: string;
  lastPage: boolean;
  members: { admitted: number; unmapped: number } | null;
  acl: AclState | null;
};

const count = (value: unknown) => (typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0);

const SKIP_WORDS: Record<string, string> = {
  record_without_id: "without an id",
  record_unversioned: "without Updated or Version",
};

function rolesOf(acl: unknown): string[] {
  const principals = record(acl).principals;
  return Array.isArray(principals)
    ? principals.map(str).filter((entry) => entry.startsWith("role:")).map((entry) => entry.slice(5))
    : [];
}

/** Who finds an item after a sync, from its ACL facet: everyone, or the people holding one of its roles. */
export function whoFinds(acl: unknown, hidden: boolean): string {
  const facet = record(acl);
  if (facet.audience === "scope") return "Everyone in the Workspace";
  const roles = rolesOf(acl);
  if (!roles.length) return "Nobody: no role's grant admits this record.";
  const list = roles.join(", ");
  return hidden ? `Hidden from you: only the role${roles.length === 1 ? "" : "s"} ${list} may read it, and you hold none of them.`
    : `People with the role${roles.length === 1 ? "" : "s"} ${list}`;
}

/** One sample item's excerpt: shown as the server sent it (already masked and cut), or why there is none. */
export function sampleExcerpt(item: Record<string, unknown>): { excerpt: string | null; excerptNote: string | null } {
  if (item.hidden === true) return { excerpt: null, excerptNote: null };
  if (typeof item.excerpt_reason === "string" && item.excerpt_reason) {
    return { excerpt: null, excerptNote: `Its content could not be read: ${restReasonText(item.excerpt_reason)}.` };
  }
  // Markdown heading marks read as noise in one quiet line; the rest is shown as sent ("[redacted]" included).
  const text = typeof item.excerpt === "string" ? item.excerpt.replace(/(^|\s)#{1,6}\s+/g, "$1").trim() : "";
  if (text) return { excerpt: text, excerptNote: null };
  return { excerpt: null, excerptNote: typeof item.excerpt === "string" ? "The content is empty."
    : "No text preview: the content is not text and is parsed during a sync." };
}

export function aclStateOf(value: unknown): AclState | null {
  const acl = record(value);
  if (typeof acl.acl_enforced !== "boolean") return null;
  return { visibility: acl.visibility === "workspace" ? "workspace" : "restricted", acl_enforced: acl.acl_enforced,
    restricted_items_withheld: acl.restricted_items_withheld === true, note: typeof acl.note === "string" ? acl.note : null };
}

/** The dry run's answer (`POST …/connectors/{key}/sample`) as the form shows it. */
export function restSampleView(answer: Record<string, unknown>): RestSampleView {
  const items = Array.isArray(answer.items) ? (answer.items as unknown[]).map(record) : [];
  const rows = items.map((item) => {
    const hidden = item.hidden === true;
    return { id: str(item.external_id), title: hidden ? "" : str(item.title), url: hidden ? "" : str(item.source_url),
      updated: hidden ? "" : str(item.source_changed_at), hidden, who: whoFinds(item.acl, hidden), ...sampleExcerpt(item) };
  });
  const skippedList = Array.isArray(answer.skipped) ? (answer.skipped as unknown[]).map(record) : [];
  const bySkip = new Map<string, number>();
  for (const entry of skippedList) {
    const reason = str(entry.reason);
    bySkip.set(reason, (bySkip.get(reason) ?? 0) + 1);
  }
  const listing = record(answer.listing);
  const members = record(answer.first_item_members);
  return {
    rows,
    listed: count(answer.listed) || rows.length,
    hidden: rows.filter((row) => row.hidden).length,
    skipped: skippedList.length,
    skippedReasons: [...bySkip].map(([reason, n]) => `${n} ${SKIP_WORDS[reason] ?? reason.replace(/_/g, " ")}`),
    dropped: count(listing.dropped_out_of_scope),
    role: str(listing.role),
    lastPage: answer.last_page === true,
    members: typeof members.admitted === "number" ? { admitted: count(members.admitted), unmapped: count(members.unmapped) } : null,
    acl: aclStateOf(answer.acl),
  };
}

// ---- status and ACL notice ----------------------------------------------------------------------------------------

// The notice links platform admins to the switch on this page; everyone else is told whom to ask.
export type AclNotice = { title: string; text: string; alternative: string };

/** The notice when restricted items are held back because the Workspace does not enforce source permissions. */
export function aclNotice(acl: AclState | null): AclNotice | null {
  if (!acl?.restricted_items_withheld) return null;
  return {
    title: "Restricted items are held back",
    text: "This Workspace does not enforce source permissions yet, so no item that is restricted by grant is indexed. "
      + "The source runs, but people find nothing from it.",
    alternative: "Or a platform admin makes this source visible to everyone in the Workspace.",
  };
}

export type RestStatus = {
  readAs: string;
  reads: string;
  visibility: string;
  nextSync: string | null;
  errors: string;
  acl: AclState | null;
  notice: AclNotice | null;
};

/** The REST-specific lines of a source's status (`GET …/connectors/{key}`): what it reads, as whom, errors, next sync. */
export function restStatus(connector: Record<string, unknown>): RestStatus {
  const scope = record(connector.scope);
  const run = record(connector.last_run);
  const report = record(run.report);
  const schedule = record(connector.schedule);
  const failed = count(report.failed);
  const acl = aclStateOf(connector.acl);
  const reason = str(run.reason);
  const errors = run.state === "failed" || run.state === "needs_configuration"
    ? `The last sync failed: ${restReasonText(reason) || "no reason given"}.`
    : failed ? `${failed} item${failed === 1 ? "" : "s"} failed in the last sync.` : "None";
  // Records the mapping could not read are not errors of the API, but the author should see them.
  const skippedRecords = Object.entries(record(report.skipped_reasons)).filter(([reason]) => SKIP_WORDS[reason])
    .map(([reason, n]) => `${count(n)} ${SKIP_WORDS[reason]}`).filter((text) => !text.startsWith("0 "));
  const detail = str(scope.detail_operation);
  return {
    readAs: str(scope.role) || "Any granted role",
    reads: [str(scope.definition), str(scope.operation)].filter(Boolean).join(" · ") + (detail ? `, content from ${detail}` : ""),
    visibility: (acl?.visibility ?? scope.visibility) === "workspace" ? `Whole Workspace. ${WORKSPACE_TEXT}` : `Restricted by grant. ${RESTRICTED_TEXT}`,
    nextSync: schedule.enabled === true && typeof schedule.next_run_at === "string" && schedule.next_run_at ? schedule.next_run_at : null,
    errors: skippedRecords.length ? `${errors}${errors.endsWith(".") ? "" : "."} Skipped: ${skippedRecords.join(", ")}.` : errors,
    acl,
    notice: aclNotice(acl),
  };
}
