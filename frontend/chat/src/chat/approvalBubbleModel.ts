// An inline approval's text parts: the reason's summary, command and analyzers, the preview record and the status line.
import type { ApprovalSummary } from "../chatDecisionTypes";
import { formatChatShortDateTime } from "./chatTimestamp";

export function formatShortDateTime(value: string | null) {
  return formatChatShortDateTime(value, value || "");
}

export function parseReason(value: string | null | undefined) {
  const lines = String(value || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const summary =
    lines.find(
      (line) => !/^command:/i.test(line) && !/^analyzers:/i.test(line),
    ) ||
    lines[0] ||
    "";
  const command =
    lines
      .find((line) => /^command:/i.test(line))
      ?.replace(/^command:\s*/i, "") || "";
  const analyzers =
    lines
      .find((line) => /^analyzers:/i.test(line))
      ?.replace(/^analyzers:\s*/i, "") || "";
  return {
    summary,
    command,
    analyzers,
    raw: lines.join("\n"),
  };
}

export function readPreviewRecord(preview: ApprovalSummary["changePreview"]) {
  const payload = preview?.preview;
  if (!payload || typeof payload !== "object") {
    return null;
  }
  return payload as Record<string, unknown>;
}

export function approvalEyebrow(status: string) {
  if (status === "approved") {
    return "Approval completed";
  }
  if (status === "rejected") {
    return "Approval denied";
  }
  if (status === "expired") {
    return "Approval timed out";
  }
  return "Human approval required";
}
