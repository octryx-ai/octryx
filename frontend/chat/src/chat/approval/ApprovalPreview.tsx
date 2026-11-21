import { useState } from "react";

import type { ApprovalSummary } from "../../chatDecisionTypes";
import { RedactedText } from "../redaction/RedactedText";
import { RestRequestPreview } from "./RestRequestPreview";
import { restRequestView } from "./restRequestView";

// The change an approval asks for, as the server stored it (masked since): a REST request in its own layout,
// otherwise the generic preview (title, summary, command, before and after, details lines). The chat's approval card
// and the approval detail page share it; only the chat offers "Retry from preview". The approval's title is the card's or
// page's own (the server's words), so the preview does not repeat it.
export function ApprovalPreview({
  preview,
  onRetryFromPreview,
  retryPrompt,
  actionsDisabled = false,
  details: servedDetails = null,
}: {
  preview: ApprovalSummary["changePreview"];
  // The server's readable detail lines (`approval/presentation.approval_texts`), served with every approval.
  details?: string[] | null;
  onRetryFromPreview?: (previewId: string, prompt: string) => Promise<void>;
  retryPrompt?: string | null;
  actionsDisabled?: boolean;
}) {
  const [retrying, setRetrying] = useState(false);
  const payload = preview?.preview;
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const previewId = String(preview?.id || "").trim();
  const record = payload as Record<string, unknown>;
  // A custom REST write (backend): the request it would send, readable, masked by the server.
  const restView = restRequestView(record);
  if (restView) return <RestRequestPreview view={restView} />;
  const summary = typeof record.summary === "string" ? record.summary : "";
  const command = typeof record.command === "string" ? record.command : "";
  const cwd = typeof record.cwd === "string" ? record.cwd : "";
  const path = typeof record.path === "string" ? record.path : "";
  const before =
    record.before && typeof record.before === "object"
      ? JSON.stringify(record.before, null, 2)
      : "";
  const after =
    record.after && typeof record.after === "object"
      ? JSON.stringify(record.after, null, 2)
      : "";
  const details = (servedDetails ?? [])
    .filter(Boolean);

  async function triggerRetryFromPreview() {
    if (
      !previewId ||
      !onRetryFromPreview ||
      !retryPrompt ||
      actionsDisabled ||
      retrying
    ) {
      return;
    }
    setRetrying(true);
    try {
      await onRetryFromPreview(previewId, retryPrompt);
    } finally {
      setRetrying(false);
    }
  }

  return (
    <section className="approval-preview">
      {summary ? (
        <div className="approval-preview__header">
          <div className="approval-preview__summary"><RedactedText value={summary} /></div>
        </div>
      ) : null}
      {previewId && retryPrompt && onRetryFromPreview ? (
        <div className="approval-preview__actions">
          <button
            type="button"
            className="plain-button approval-card__button approval-card__button--retry"
            disabled={actionsDisabled || retrying}
            onClick={() => void triggerRetryFromPreview()}
          >
            {retrying ? "Rerunning…" : "Retry from preview"}
          </button>
        </div>
      ) : null}
      {command ? <pre className="approval-preview__code"><RedactedText value={command} /></pre> : null}
      {cwd || path ? (
        <div className="approval-preview__meta">
          {cwd ? <span>cwd: {cwd}</span> : null}
          {path ? <span>path: {path}</span> : null}
        </div>
      ) : null}
      {before ? (
        <details className="approval-preview__details">
          <summary>Before</summary>
          <pre className="approval-preview__code"><RedactedText value={before} /></pre>
        </details>
      ) : null}
      {after ? (
        <details className="approval-preview__details" open>
          <summary>Planned change</summary>
          <pre className="approval-preview__code"><RedactedText value={after} /></pre>
        </details>
      ) : null}
      {details.length ? (
        <ul className="approval-preview__list">
          {details.map((item, index) => (
            <li key={`${item}-${index}`}><RedactedText value={item} /></li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
