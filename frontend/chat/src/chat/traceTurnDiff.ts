// Turn diff readers: commands, file changes and policy events, their badge tone and preview text, working-set stats.
import type { TurnTrace } from "../chatThreadTypes";

export function normalizeTurnDiff(
  value: Record<string, unknown> | null | undefined,
): {
  commands: Array<Record<string, unknown>>;
  fileChanges: Array<Record<string, unknown>>;
  policyEvents: Array<Record<string, unknown>>;
} {
  return {
    commands: Array.isArray(value?.commands)
      ? (value.commands as Array<Record<string, unknown>>)
      : [],
    fileChanges: Array.isArray(value?.file_changes)
      ? (value.file_changes as Array<Record<string, unknown>>)
      : [],
    policyEvents: Array.isArray(value?.policy_events)
      ? (value.policy_events as Array<Record<string, unknown>>)
      : [],
  };
}

export function turnDiffBadgeTone(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (
    normalized === "allow" ||
    normalized === "allowed" ||
    normalized === "success" ||
    normalized === "created" ||
    normalized === "updated" ||
    normalized === "modified"
  ) {
    return "success";
  }
  if (
    normalized === "review" ||
    normalized === "pending" ||
    normalized === "warning"
  ) {
    return "warning";
  }
  if (
    normalized === "deny" ||
    normalized === "denied" ||
    normalized === "rejected" ||
    normalized === "failed" ||
    normalized === "deleted" ||
    normalized === "removed"
  ) {
    return "danger";
  }
  return "muted";
}

export function summarizeTurnDiffEntry(
  entry: Record<string, unknown>,
  type: "command" | "file" | "policy",
) {
  if (type === "command") {
    const command =
      typeof entry.command === "string" ? entry.command.trim() : "";
    if (command) {
      return command;
    }
    return "Command";
  }
  if (type === "file") {
    const path = typeof entry.path === "string" ? entry.path.trim() : "";
    const details =
      typeof entry.details === "string" ? entry.details.trim() : "";
    if (path && details) {
      return `${path} · ${details}`;
    }
    return path || details || "File change";
  }
  const action = typeof entry.action === "string" ? entry.action.trim() : "";
  const reason = typeof entry.reason === "string" ? entry.reason.trim() : "";
  const command = typeof entry.command === "string" ? entry.command.trim() : "";
  return command || reason || action || "Policy event";
}

export function summarizeTurnDiffPreview(
  commands: Array<Record<string, unknown>>,
  fileChanges: Array<Record<string, unknown>>,
  policyEvents: Array<Record<string, unknown>>,
) {
  const previews: string[] = [];
  if (commands.length) {
    previews.push(summarizeTurnDiffEntry(commands[0], "command"));
  }
  if (fileChanges.length) {
    previews.push(summarizeTurnDiffEntry(fileChanges[0], "file"));
  }
  if (policyEvents.length) {
    previews.push(summarizeTurnDiffEntry(policyEvents[0], "policy"));
  }
  return previews.filter(Boolean);
}

export function extractWithinTurnWorkingSetStats(trace: TurnTrace) {
  const snapshot = (trace.contextSnapshot ?? {}) as Record<string, unknown>;
  const stats = snapshot.within_turn_working_set;
  if (!stats || typeof stats !== "object" || Array.isArray(stats)) {
    return null;
  }
  return stats as Record<string, unknown>;
}

export function extractWithinTurnWorkingSummary(trace: TurnTrace) {
  const snapshot = (trace.contextSnapshot ?? {}) as Record<string, unknown>;
  const summary = snapshot.within_turn_working_summary;
  return typeof summary === "string" && summary.trim() ? summary : null;
}
