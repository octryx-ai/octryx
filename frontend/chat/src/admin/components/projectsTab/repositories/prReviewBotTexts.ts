// PR review bot › the panel's option texts and hints. Data only.
import type { BotStatusPolicy, BotTrigger } from "./prReviewBotModel";

export const TRIGGER_OPTIONS: Record<BotTrigger, { title: string; desc: string; short: string; recommended?: boolean }> = {
  off: { title: "Off", desc: "Nothing is reviewed or posted on this repository.", short: "Off" },
  webhook: { title: "On every push (webhook)", desc: "Each pull request event starts a review at once.", short: "Webhook" },
  sync: { title: "Hourly sync", desc: "Open pull requests are checked once an hour.", short: "Hourly sync" },
  both: { title: "Webhook and hourly sync", desc: "Reviews at once; the hourly sync catches what a webhook missed.",
    short: "Webhook and sync", recommended: true },
};

export const STATUS_OPTIONS: Record<BotStatusPolicy, { title: string; desc: string; short: string; recommended?: boolean }> = {
  inform: { title: "Inform", recommended: true, short: "Informs",
    desc: "The octryx/review status passes and counts the findings. It fails only for a committed secret." },
  gate: { title: "Required check", short: "Required check",
    desc: "The status fails when the review finds a blocking problem (high or medium)." },
};
export const GATE_HINT = "It blocks a merge only where the repository's branch protection (or GitLab's \"Pipelines must "
  + "succeed\") requires the octryx/review status.";

export const BOT_INTRO = "Octryx reviews the pull requests of these repositories with its independent reviewer: one "
  + "summary comment, inline comments and the octryx/review status. It never approves, pushes or merges.";
export const WEBHOOK_HINT = "Webhook needs the Workspace's pull request webhook (Admin → Webhooks).";
export const BRANCHES_HINT = "Octryx only opens pull requests into these branches, never pushes.";
export const DRAFTS_HINT = "Without it, a draft is reviewed once it is ready for review.";
