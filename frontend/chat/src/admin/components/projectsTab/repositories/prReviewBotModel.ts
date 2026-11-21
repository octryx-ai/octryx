// Workspace settings › Repositories › "PR review bot": the bot's settings per GitHub/GitLab/Bitbucket repository (backend
// routes api/routes/pr_review_bot.py). Pure: no React.
//
// - GET  /api/v1/workspaces/<ws>/pr-review-bot: every repository the bot can post on, with its settings, the
//   triggers the server knows, whether the caller may change them (`can_edit`) and whether the Workspace has an
//   active pull request webhook (`webhook_configured`). One read for all rows.
// - PUT  …/repositories/<id>/pr-review-bot: changes the fields it is sent; the panel still sends every field
//   it edits plus the ones it does not (`kept`, sent back as they were); answers with the repository row.
// - POST …/repositories/<id>/pr-review-bot/sync: the hourly sync now (admins, stored trigger `sync` or `both`).
// Refusals are `{state: "denied", reason, path?}`. Fix runs, the size brake and hotspot paths: prReviewBotLimits.ts.

import {
  DEFAULT_LIMITS, LIMIT_KEYS, botLimitsBody, botLimitsProblems, limitsSaveError, readBotLimits, sameBotLimits,
  type BotLimits, type LimitField,
} from "./prReviewBotLimits";
import { WEBHOOK_HINT } from "./prReviewBotTexts";

export type BotTrigger = "off" | "webhook" | "sync" | "both";
export const BOT_TRIGGERS: readonly BotTrigger[] = ["off", "webhook", "sync", "both"];

/** What the commit status octryx-review says: `inform` (default) never blocks except for a committed secret; `gate`
 *  fails on blocking findings. */
export type BotStatusPolicy = "inform" | "gate";
export const BOT_STATUS_POLICIES: readonly BotStatusPolicy[] = ["inform", "gate"];

export type BotSettings = BotLimits & {
  trigger: BotTrigger;
  protectedBranches: string[];
  reviewDrafts: boolean;
  statusPolicy: BotStatusPolicy;
  /** The stored settings this panel does not edit, sent back unchanged (the PUT replaces the whole object). */
  kept?: Record<string, unknown>;
};
export type BotRepository = { id: string; name: string; repository: string; settings: BotSettings };
export type BotPayload = {
  repositories: BotRepository[];
  triggers: BotTrigger[];
  canEdit: boolean;
  webhookConfigured: boolean;
};

export type BotField = "trigger" | "protectedBranches" | "reviewDrafts" | "statusPolicy" | LimitField | "general";
/** Errors at their field; `branches` / `hotspots` hold a message per offending entry (shown at its chip). */
export type BotErrors = Partial<Record<BotField, string>> & { branches?: Record<string, string>;
  hotspots?: Record<string, string> };

export const OFF_SETTINGS: BotSettings = { trigger: "off", protectedBranches: [], reviewDrafts: false, statusPolicy: "inform",
  ...DEFAULT_LIMITS, kept: {} };

const EDITED = new Set<string>(["trigger", "protected_branches", "review_drafts", "status_policy", ...LIMIT_KEYS]);
const isTrigger = (value: unknown): value is BotTrigger => BOT_TRIGGERS.includes(value as BotTrigger);
const isStatusPolicy = (value: unknown): value is BotStatusPolicy => BOT_STATUS_POLICIES.includes(value as BotStatusPolicy);
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};

/** A stored settings object, read the way the server reads a stored record: anything unknown falls back to off. */
export function readBotSettings(raw: unknown): BotSettings {
  const stored = record(raw);
  const trigger = String(stored.trigger ?? "off").trim().toLowerCase();
  const branches = Array.isArray(stored.protected_branches)
    ? stored.protected_branches.filter((item): item is string => typeof item === "string").map((item) => item.trim()).filter(Boolean)
    : [];
  const policy = String(stored.status_policy ?? "inform").trim().toLowerCase();
  return {
    trigger: isTrigger(trigger) ? trigger : "off",
    protectedBranches: [...new Set(branches)],
    reviewDrafts: stored.review_drafts === true,
    statusPolicy: isStatusPolicy(policy) ? policy : "inform",
    ...readBotLimits(stored),
    kept: Object.fromEntries(Object.entries(stored).filter(([key]) => !EDITED.has(key))),
  };
}

/** The PUT's answer: the row and the Workspace's webhook state (null when the answer does not carry it). */
export function readBotSaved(raw: unknown): { row: BotRepository; webhookConfigured: boolean | null } | null {
  const row = readBotRepository(raw);
  const webhook = record(raw).webhook_configured;
  return row ? { row, webhookConfigured: typeof webhook === "boolean" ? webhook : null } : null;
}

/** One repository row (the GET's entries and the PUT's answer); null without an id. */
export function readBotRepository(raw: unknown): BotRepository | null {
  const row = record(raw);
  const id = typeof row.id === "string" ? row.id : "";
  if (!id) return null;
  const repository = typeof row.repository === "string" ? row.repository : "";
  return { id, name: typeof row.name === "string" && row.name ? row.name : repository || id, repository,
    settings: readBotSettings(row.settings) };
}

export function readBotPayload(raw: unknown): BotPayload {
  const payload = record(raw);
  const rows = Array.isArray(payload.repositories) ? payload.repositories : [];
  const offered = Array.isArray(payload.triggers) ? payload.triggers.filter(isTrigger) : [];
  return {
    repositories: rows.map(readBotRepository).filter((row): row is BotRepository => row !== null),
    // The UI order is the contract's (Off first); only what the server knows is offered.
    triggers: offered.length ? BOT_TRIGGERS.filter((trigger) => offered.includes(trigger)) : [...BOT_TRIGGERS],
    canEdit: payload.can_edit === true,
    webhookConfigured: payload.webhook_configured === true,
  };
}

/** The PUT body: every field, the edited ones and the kept ones, because the PUT replaces the whole settings object
 *  (a save here reset fix_runs and the size limits to their defaults). */
export function botSettingsBody(settings: BotSettings): Record<string, unknown> & {
  trigger: BotTrigger; protected_branches: string[]; review_drafts: boolean; status_policy: BotStatusPolicy;
} {
  return {
    ...(settings.kept ?? {}),
    trigger: settings.trigger,
    protected_branches: settings.protectedBranches.map((branch) => branch.trim()),
    review_drafts: settings.reviewDrafts,
    status_policy: settings.statusPolicy,
    ...botLimitsBody(settings),
  };
}

export const sameBotSettings = (a: BotSettings, b: BotSettings) =>
  a.trigger === b.trigger && a.reviewDrafts === b.reviewDrafts && a.statusPolicy === b.statusPolicy && sameBotLimits(a, b)
  && a.protectedBranches.length === b.protectedBranches.length
  && a.protectedBranches.every((branch, index) => branch.trim() === b.protectedBranches[index]?.trim());

export const MAX_BRANCH = 255;

/** Why a branch name is refused, or null: the server's rules (empty, too long, whitespace, `..`, listed twice). */
export function branchProblem(name: string, earlier: readonly string[]): string | null {
  const branch = name.trim();
  if (!branch) return "A branch name cannot be empty.";
  if (branch.length > MAX_BRANCH) return `A branch name has at most ${MAX_BRANCH} characters.`;
  if (/\s/.test(branch)) return "A branch name has no spaces.";
  if (branch.includes("..")) return "A branch name cannot contain “..”.";
  if (earlier.some((item) => item.trim() === branch)) return "This branch is listed twice.";
  return null;
}

/** The draft's problems at their fields (per branch for the chips); empty when it can be saved. */
export function botSettingsProblems(settings: BotSettings): BotErrors {
  const branches: Record<string, string> = {};
  settings.protectedBranches.forEach((branch, index) => {
    const problem = branchProblem(branch, settings.protectedBranches.slice(0, index));
    if (problem && !branches[branch]) branches[branch] = problem;
  });
  return { ...botLimitsProblems(settings), ...(Object.keys(branches).length ? { branches } : {}) };
}

export const hasBotErrors = (errors: BotErrors) =>
  Object.entries(errors).some(([key, value]) => key === "branches" || key === "hotspots"
    ? Object.keys(value ?? {}).length > 0 : Boolean(value));

const PATH = /^protected_branches\[(\d+)\]$/;

/** A refused save in words, at its field (a refused branch at its chip). */
export function botSaveErrors(status: number, body: unknown, sent: BotSettings): BotErrors {
  const refusal = record(body);
  const reason = typeof refusal.reason === "string" ? refusal.reason : "";
  if (status === 0) return { general: "Not saved: the request did not reach the server." };
  if (reason === "protected_branch_invalid") {
    const index = PATH.exec(String(refusal.path ?? ""))?.[1];
    const branch = index === undefined ? undefined : sent.protectedBranches[Number(index)];
    if (branch !== undefined) {
      return { branches: { [branch]: branchProblem(branch, sent.protectedBranches.slice(0, Number(index)))
        ?? "The server did not accept this branch name." } };
    }
    return { protectedBranches: "The server did not accept one of these branch names." };
  }
  if (reason === "protected_branches_not_a_list") return { protectedBranches: "The server did not accept this list. Use plain branch names." };
  const limits = limitsSaveError(reason, refusal.path);
  if (limits) return limits;
  if (reason === "status_policy_unknown") {
    return { statusPolicy: "The server does not know this choice. Reload the page and choose again." };
  }
  if (reason === "trigger_unknown") return { trigger: "The server does not know this choice. Reload the page and choose again." };
  if (reason === "settings_not_an_object") return { general: "Not saved: the settings did not arrive as a whole. Reload and try again." };
  if (reason === "workspace_admin_required" || status === 403) {
    return { general: "Not saved: only a Workspace admin or owner can change the review bot." };
  }
  if (reason === "repository_not_found") {
    return { general: "Not saved: this repository is no longer in the Workspace on GitHub, GitLab or Bitbucket. Reload the page." };
  }
  if (reason === "workspace_not_found") return { general: "Not saved: this Workspace no longer exists, or you are no longer a member." };
  if (status === 400) return { general: "Not saved: the server refused these settings." };
  return { general: "Not saved: the server did not answer. Try again." };
}

/** The GET's outcome: the payload, a sentence, or `unavailable` (the server has no review bot: route missing). */
export function botLoadProblem(status: number, body: unknown): { kind: "unavailable" } | { kind: "error"; text: string } {
  const reason = record(body).reason;
  if (status === 404 && reason === undefined) return { kind: "unavailable" };
  if (reason === "workspace_not_found") return { kind: "error", text: "This Workspace no longer exists, or you are no longer a member." };
  if (status === 0) return { kind: "error", text: "The review bot settings could not be loaded: the request did not reach the server." };
  return { kind: "error", text: "The review bot settings could not be loaded. Try again." };
}

export const usesWebhook = (trigger: BotTrigger) => trigger === "webhook" || trigger === "both";
export const usesSync = (trigger: BotTrigger) => trigger === "sync" || trigger === "both";

/** The line under the trigger choice: a problem when the chosen trigger needs a webhook the Workspace lacks. */
export function webhookLine(trigger: BotTrigger, webhookConfigured: boolean): { tone: "problem" | "quiet"; text: string } {
  if (usesWebhook(trigger) && !webhookConfigured) {
    return { tone: "problem", text: "No pull request webhook in this Workspace yet: Admin → Webhooks." };
  }
  if (webhookConfigured) return { tone: "quiet", text: "The Workspace's pull request webhook is set up." };
  return { tone: "quiet", text: WEBHOOK_HINT };
}

/** What a person may do with one row: everything is read-only without `can_edit`; "Sync now" needs the stored
 * trigger to sync (the server checks the stored settings, so an unsaved change must be saved first). */
export function botControls(canEdit: boolean, stored: BotSettings, changed: boolean, busy: boolean) {
  const syncReady = canEdit && usesSync(stored.trigger) && !changed;
  return {
    disabled: !canEdit || busy,
    showSave: canEdit && changed,
    showSync: canEdit,
    syncDisabled: busy || !syncReady,
    syncHint: !canEdit ? null : !usesSync(stored.trigger) ? "Sync now needs “Hourly sync” or “Webhook and hourly sync”, saved."
      : changed ? "Save first: Sync now uses the saved settings." : null,
    readOnlyNote: canEdit ? null : "Only a Workspace admin or owner can change the review bot.",
  };
}

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const counts = (raw: unknown): Record<string, number> => Object.fromEntries(Object.entries(record(raw))
  .filter((entry): entry is [string, number] => typeof entry[1] === "number" && entry[1] > 0));

// The skip reasons of a sync (backend pr_review_bot/starter.py); an unknown reason shows by its key.
const SKIP_WORDS: Record<string, (n: number) => string> = {
  draft: (n) => `${count(n, "draft", "drafts")} (review drafts is off)`,
  fork: (n) => `${n} from ${n === 1 ? "a fork" : "forks"} (not reviewed yet)`,
  no_head: (n) => `${n} without a head commit (the provider named none)`,
};

/** The skipped heads in words: "Skipped 3: 1 draft (review drafts is off), 2 from forks (not reviewed yet)". */
export function skippedText(skipped: number, reasons: unknown): string {
  const byReason = counts(reasons);
  const parts = Object.entries(byReason).map(([reason, n]) => (SKIP_WORDS[reason] ?? ((k) => `${k} ${reason}`))(n));
  const total = Math.max(skipped, Object.values(byReason).reduce((sum, n) => sum + n, 0));
  const rest = total - Object.values(byReason).reduce((sum, n) => sum + n, 0);
  if (rest > 0 && parts.length) parts.push(`${rest} other`);
  return parts.length ? `Skipped ${total}: ${parts.join(", ")}.` : `Skipped ${total}.`;
}

/** The sync's answer in words (`already_reviewed`: a run reviewed that head before). */
export function syncResultText(body: unknown): string {
  const answer = record(body);
  const outcomes = counts(answer.outcomes);
  const started = outcomes.started ?? 0; const reviewed = outcomes.already_reviewed ?? 0;
  const reasons = counts(answer.skipped_reasons);
  const skipped = Math.max(outcomes.skipped ?? 0, Object.values(reasons).reduce((sum, n) => sum + n, 0));
  if (!started && !reviewed && !skipped) return "Synced: no open pull request.";
  const parts = [
    started ? `${count(started, "review", "reviews")} started` : "",
    reviewed ? `${count(reviewed, "pull request was", "pull requests were")} already reviewed at this commit` : "",
  ].filter(Boolean);
  const head = parts.length ? `Synced: ${parts.join(", ")}.` : "Synced.";
  return skipped ? `${head} ${skippedText(skipped, reasons)}` : head;
}

/** A refused sync in words. */
export function syncErrorText(status: number, body: unknown): string {
  const reason = String(record(body).reason ?? "");
  if (status === 0) return "Not synced: the request did not reach the server.";
  if (reason === "sync_not_switched_on") return "Not synced: switch on “Hourly sync” or “Webhook and hourly sync” and save first.";
  if (reason.startsWith("pull_requests_unreadable")) {
    const detail = reason.slice(reason.indexOf(":") + 1).trim();
    return `Not synced: the provider refused to list the pull requests${detail && reason.includes(":") ? ` (${detail})` : ""}.`;
  }
  if (reason === "workspace_admin_required" || status === 403) return "Not synced: only a Workspace admin or owner can sync.";
  if (reason === "repository_not_found") return "Not synced: this repository is no longer in the Workspace. Reload the page.";
  if (reason === "workspace_not_found") return "Not synced: this Workspace no longer exists, or you are no longer a member.";
  return "Not synced: the server did not answer. Try again.";
}

const PROVIDER_LABELS: Record<string, string> = { github: "GitHub", gitlab: "GitLab", bitbucket: "Bitbucket" };

/** "GitHub" / "GitLab" / "Bitbucket" from `github:owner/repo`. */
export function providerLabel(repository: string): string {
  return PROVIDER_LABELS[repository.split(":")[0]?.toLowerCase() ?? ""] ?? "";
}
