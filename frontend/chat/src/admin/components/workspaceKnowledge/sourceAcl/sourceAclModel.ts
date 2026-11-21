// Knowledge › Sources: whether the Workspace enforces source permissions (`knowledge_source_acl.enforce`, backend
// `GET|PUT …/knowledge/source-acl`). Off, a source still runs, but every item restricted by grant is held back;
// on, those items are indexed for the members their source admits. Only a platform admin reads or changes it; a change
// needs a reason, is audited, and each source's next sync picks the items up. Pure: no React.

export type SourceAcl = {
  enforce: boolean;
  // Items the sources currently hold back for their restriction: an upper bound of what turning it on lets in.
  heldBack: number;
};

export type SourceAclPreview = {
  // What the preview asked for, and whether that is a change at all.
  requested: boolean;
  changed: boolean;
  // Held-back items that turning it on would let in (0 for turning it off).
  released: number;
};

const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
const count = (value: unknown) => (typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.floor(value) : 0);
const items = (n: number) => `${n} item${n === 1 ? "" : "s"}`;

/** The switch as the server answers it; null when the answer is not one. */
export function sourceAclOf(answer: unknown): SourceAcl | null {
  const given = record(answer);
  if (typeof given.enforce !== "boolean") return null;
  return { enforce: given.enforce, heldBack: count(given.withheld_restricted_items) };
}

/** The dry run's answer (`PUT … {dry_run: true}`): the server keeps `enforce` as it is and says what would change. */
export function sourceAclPreviewOf(answer: unknown): SourceAclPreview | null {
  const given = record(answer);
  if (typeof given.requested !== "boolean") return null;
  return { requested: given.requested, changed: given.changed === true, released: count(given.released_when_enabled) };
}

/** The request body. The reason is required by the server (422 when blank) and recorded with the change. */
export function sourceAclBody(enforce: boolean, reason: string, dryRun: boolean): { enforce: boolean; reason: string; dry_run: boolean } {
  return { enforce, reason: reason.trim(), dry_run: dryRun };
}

export const SOURCE_ACL_TITLE = "Enforce source permissions in this Workspace";
export const SOURCE_ACL_NOTE = "This is an upper bound: an item whose restriction its source cannot resolve, such as a Jira "
  + "security level, stays held back after the switch.";

/** The status lines of the switch: on or off, how many items are held back, and the note on that count. */
export function sourceAclSummary(acl: SourceAcl): { label: string; heldBack: string; note: string | null } {
  if (acl.enforce) {
    return {
      label: "On",
      // Until each source's next sync, the items held back before the switch are still counted.
      heldBack: acl.heldBack
        ? `${items(acl.heldBack)} ${acl.heldBack === 1 ? "is" : "are"} still held back. Each source's next sync picks them up.`
        : "Restricted items are indexed for the members their source admits.",
      note: acl.heldBack ? "An item whose restriction its source cannot resolve, such as a Jira security level, stays held back." : null,
    };
  }
  return {
    label: "Off",
    heldBack: acl.heldBack ? `Up to ${items(acl.heldBack)} ${acl.heldBack === 1 ? "is" : "are"} held back.` : "No item is held back right now.",
    note: acl.heldBack ? SOURCE_ACL_NOTE : null,
  };
}

/** What a preview says would happen, in words. */
export function sourceAclPreviewText(preview: SourceAclPreview): string {
  if (!preview.changed) return `Nothing would change: source permissions are already ${preview.requested ? "on" : "off"}.`;
  if (!preview.requested) {
    return "Turning it off holds restricted items back again: each source's next sync removes those already indexed from Knowledge.";
  }
  return preview.released
    ? `Turning it on lets up to ${items(preview.released)} in. Each source's next sync picks them up, readable only by the members their source admits.`
    : "Turning it on lets no held-back item in right now. Restricted items of later syncs are indexed for the members their source admits.";
}

export type SourceAclPanelView = {
  target: boolean;
  actionLabel: string;
  reasonMissing: boolean;
  previewEnabled: boolean;
  confirmEnabled: boolean;
  // Why the change button waits, when it does.
  waiting: string | null;
  previewText: string | null;
};

/** The change panel: it always offers the other state; Preview needs a reason, the change a preview of that state. */
export function sourceAclPanelView({ acl, reason, preview, busy }: {
  acl: SourceAcl; reason: string; preview: SourceAclPreview | null; busy: boolean;
}): SourceAclPanelView {
  const target = !acl.enforce;
  const reasonMissing = !reason.trim();
  const previewed = preview !== null && preview.requested === target;
  const confirmEnabled = !busy && !reasonMissing && previewed && preview.changed;
  return {
    target,
    actionLabel: target ? "Turn on" : "Turn off",
    reasonMissing,
    previewEnabled: !busy && !reasonMissing,
    confirmEnabled,
    waiting: confirmEnabled || busy ? null : reasonMissing ? "Enter a reason to continue." : previewed ? null : "Run the preview first.",
    previewText: previewed ? sourceAclPreviewText(preview) : null,
  };
}

/** The message after the change. */
export function sourceAclDoneText(enforce: boolean): string {
  return enforce
    ? "Source permissions are on. Each source's next sync picks up the held-back items."
    : "Source permissions are off. Each source's next sync holds restricted items back again.";
}

/** Every refusal of the switch in words (422 blank reason, 403 not a platform admin, 404 Workspace not reachable). */
export function sourceAclRefusal(error: unknown): string {
  const failure = (error && typeof error === "object" ? error : {}) as { status?: number; reason?: string | null; message?: string };
  const status = failure.status ?? 0;
  if (failure.reason === "source_acl_enforce_admin_only" || status === 403) {
    return "Only a platform admin can change whether this Workspace enforces source permissions.";
  }
  if (status === 422) return "Enter a reason. It is recorded in the audit log with the change.";
  if (status === 401) return "Your session ended. Sign in again.";
  if (status === 404) return "This Workspace is not available to you. A platform admin needs a role in it to change this.";
  if (status >= 500) return "The server did not answer as expected. Try again.";
  if (status >= 400) return "The server did not accept this. Reload the page and try again.";
  return "The request failed. Check your connection and try again.";
}
