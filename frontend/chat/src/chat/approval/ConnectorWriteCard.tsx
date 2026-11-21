import "./connectorWriteCard.css";
import type { ApprovalSummary } from "../../chatDecisionTypes";
import { StatusLabel } from "../../layout/StatusLabel";
import { formatChatShortDateTime } from "../chatTimestamp";
import type { ApprovalDecisionKind } from "../approvalCardActions";
import { RedactedText } from "../redaction/RedactedText";
import { connectorWriteStatus, type ConnectorWriteView } from "./connectorWriteView";

// Every field the connector write sets (masked by the server); the approval detail page shows the same list.
export function ConnectorWriteFields({ view }: { view: ConnectorWriteView }) {
  return view.fields.length ? (
    <dl className="write-approval__fields" aria-label="Fields to write">
      {view.fields.map((field, index) => (
        <div key={`${field.key}-${index}`} className="write-approval__field">
          <dt>{field.label}</dt>
          <dd><RedactedText value={field.value} /></dd>
        </div>
      ))}
    </dl>
  ) : (
    <p className="write-approval__empty">The call writes no fields.</p>
  );
}

// The confirmation of one connector write from a chat: what is written and where as the title, every field
// the call writes, then Reject and Approve. There is no "Always": every call is confirmed anew.
export function ConnectorWriteCard({
  approval,
  view,
  subtitle = "",
  onDecision,
  actionsDisabled = false,
}: {
  approval: ApprovalSummary;
  view: ConnectorWriteView;
  // Why the person is asked, one quiet line under the title.
  subtitle?: string;
  onDecision: (approval: ApprovalSummary, decision: ApprovalDecisionKind) => void;
  actionsDisabled?: boolean;
}) {
  const status = connectorWriteStatus(approval.status);
  const pending = status.tone === "attention";
  const when = formatChatShortDateTime(approval.resolvedAt || approval.createdAt, "");
  const where = [view.connector, view.connection && view.connection !== view.connector ? `connection ${view.connection}` : ""]
    .filter(Boolean)
    .join(" · ");
  return (
    <article className="message-row message-row--approval">
      <section
        className={`write-approval write-approval--${pending ? "pending" : "done"}`}
        aria-label={`Confirm: ${view.title}`}
        data-testid="connector-write-approval"
        data-status={String(approval.status || "pending").toLowerCase()}
      >
        <header className="write-approval__head">
          <div className="write-approval__heading">
            <span className="write-approval__eyebrow">
              {pending ? "Confirm before Octryx writes" : "Write request"}
            </span>
            <h3 className="write-approval__title">{view.title}</h3>
            {subtitle ? <p className="write-approval__where" data-testid="connector-write-subtitle">{subtitle}</p> : null}
            {where ? <p className="write-approval__where">Writes to {where}</p> : null}
          </div>
          <StatusLabel label={status.label} tone={status.tone} testId="connector-write-status" />
        </header>
        <ConnectorWriteFields view={view} />
        <footer className="write-approval__foot">
          <span className="write-approval__note">
            {pending ? "Only this call. The next write asks again." : when ? `${status.label} ${when}` : status.label}
          </span>
          {pending ? (
            <div className="write-approval__actions">
              <button
                type="button"
                className="admin-panel__action-btn"
                disabled={actionsDisabled}
                onClick={() => onDecision(approval, "reject")}
              >
                Reject
              </button>
              <button
                type="button"
                className="admin-panel__action-btn admin-panel__action-btn--primary"
                disabled={actionsDisabled}
                onClick={() => onDecision(approval, "approve")}
              >
                Approve
              </button>
            </div>
          ) : null}
        </footer>
      </section>
    </article>
  );
}
