// The derived lines of the inline approval card: status, why, meta and the governed change's preview fields.
import type { ApprovalSummary } from "../chatDecisionTypes";
import { formatShortDateTime, parseReason, type readPreviewRecord } from "./approvalBubbleModel";
import { restRequestView } from "./approval/restRequestView";

type PreviewRecord = ReturnType<typeof readPreviewRecord>;

function previewText(previewRecord: PreviewRecord, key: "summary" | "cwd" | "path"): string {
  return previewRecord && typeof previewRecord[key] === "string" ? (previewRecord[key] as string) : "";
}

export function approvalInlineView(
  approval: ApprovalSummary,
  previewRecord: PreviewRecord,
  subtitle: string,
) {
  const approvalStatus = String(approval.status || "pending")
    .trim()
    .toLowerCase();
  const reasonMeta = parseReason(approval.reason);
  // A REST write's request is what the person decides on, so its preview starts open.
  const restView = restRequestView(previewRecord);
  const previewCommand =
    (previewRecord &&
      typeof previewRecord.command === "string" &&
      previewRecord.command) ||
    reasonMeta.command;
  const requestFingerprint = String(
    approval.changePreview?.requestFingerprint || "",
  ).trim();
  // The title says what runs (the server's words); the line above it says where the approval stands.
  const metaLabel = restView?.target ?? "";
  return {
    approvalStatus,
    reasonMeta,
    isRestRequest: restView !== null,
    previewSummary: previewText(previewRecord, "summary"),
    previewCommand,
    previewCwd: previewText(previewRecord, "cwd"),
    previewPath: previewText(previewRecord, "path"),
    metaLabel,
    // The subtitle is why the person is asked; the reason's first line only when the server gave none.
    whyLine: subtitle || reasonMeta.summary,
    timestampLabel: formatShortDateTime(approval.createdAt),
    shortFingerprint: requestFingerprint ? requestFingerprint.slice(0, 16) : "",
  };
}

export type ApprovalInlineView = ReturnType<typeof approvalInlineView>;
