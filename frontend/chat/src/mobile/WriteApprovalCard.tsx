// A Server chat's connector write on the phone (the web's ConnectorWriteCard and its model): what is written and
// where, every field, then Reject and Approve. Only this call; the next write asks again. "Always" stays in the web.

import { useState } from "react";
import { StatusLabel } from "../layout/StatusLabel";
import {
  connectorWriteStatus,
  connectorWriteView,
  type ConnectorWriteView,
} from "../chat/approval/connectorWriteView";
import { decideChatApproval } from "./mobileApi";
import { type MobileError } from "./mobileSession";
import { RedactedText } from "../chat/redaction/RedactedText";
import { decisionErrorText } from "./phoneApprovals";

export type PendingWrite = { id: string; status: string; view: ConnectorWriteView };

const record = (value: unknown) => (value && typeof value === "object" ? (value as Record<string, unknown>) : null);

/** The chat's connector writes that wait for the person (other approvals are not answered on the phone). */
export function pendingWrites(approvals: unknown): PendingWrite[] {
  return (Array.isArray(approvals) ? approvals : []).flatMap((raw) => {
    const approval = record(raw);
    const change = record(approval?.changePreview);
    const view = connectorWriteView(record(change?.preview), typeof change?.toolName === "string" ? change.toolName : null);
    const status = String(approval?.status ?? "pending");
    if (!approval || typeof approval.id !== "string" || !view || connectorWriteStatus(status).tone !== "attention") return [];
    // The server's title for it, else the preview's own.
    const title = typeof approval.title === "string" && approval.title.trim() ? approval.title : view.title;
    return [{ id: approval.id, status, view: { ...view, title } }];
  });
}

export function WriteApprovalCard({ write, onDecided }: { write: PendingWrite; onDecided: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { view } = write;
  const status = connectorWriteStatus(write.status);
  const where = [view.connector, view.connection && view.connection !== view.connector ? `connection ${view.connection}` : ""]
    .filter(Boolean)
    .join(" · ");
  const decide = async (decision: "approve" | "reject") => {
    setBusy(true);
    setError("");
    try {
      await decideChatApproval(write.id, decision);
      onDecided();
    } catch (reason) {
      const failure = reason as MobileError;
      setError(decisionErrorText("reject", failure.status, failure.detail ?? "", failure.code));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="m-write" aria-label={`Confirm: ${view.title}`} data-testid="m-write-approval">
      <header className="m-write-head">
        <span className="m-eyebrow">Confirm before Octryx writes</span>
        <StatusLabel label={status.label} tone={status.tone} />
      </header>
      <h2>{view.title}</h2>
      {where && <p className="m-muted">Writes to {where}</p>}
      {view.fields.length ? (
        <dl className="m-write-fields" aria-label="Fields to write">
          {view.fields.map((field, index) => (
            <div key={`${field.key}-${index}`}>
              <dt>{field.label}</dt>
              <dd><RedactedText value={field.value} /></dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="m-muted">The call writes no fields.</p>
      )}
      <p className="m-muted">Only this call. The next write asks again.</p>
      <div className="m-buttons">
        <button type="button" className="m-secondary" disabled={busy} onClick={() => void decide("reject")}>
          Reject
        </button>
        <button type="button" className="m-primary" disabled={busy} onClick={() => void decide("approve")}>
          Approve
        </button>
      </div>
      {error && (
        <p className="m-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
