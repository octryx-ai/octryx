import { useState } from "react";

import "./writePlanCard.css";
import type { ApprovalSummary } from "../../chatDecisionTypes";
import { StatusLabel } from "../../layout/StatusLabel";
import type { ApprovalDecisionKind } from "../approvalCardActions";
import { RedactedText } from "../redaction/RedactedText";
import {
  WRITE_PLAN_NOTE,
  countLabel,
  writePlanResult,
  type WritePlanScopeGroup,
  type WritePlanView,
  type WritePlanWrite,
} from "./writePlanView";

// A chat's write plan: the scope first, every intended write with its fields in
// full, then one Reject and one Approve. Confirmed once, everything inside the scope runs without asking again.
// There is no "Always" and no per-call exception.
export function WritePlanScope({ groups }: { groups: WritePlanScopeGroup[] }) {
  if (!groups.length) return null;
  return (
    <dl className="write-plan__scope" aria-label="Scope of the plan">
      {groups.map((group) => (
        <div key={group.key} className="write-plan__scope-group">
          <dt>{group.label}</dt>
          <dd>
            {group.chips.map((chip) => (
              <span key={`${chip.kind}-${chip.value}`} className="write-plan__chip" title={chip.text}>
                {chip.text}
              </span>
            ))}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function WritePlanWriteBody({ write }: { write: WritePlanWrite }) {
  return (
    <div className="write-plan__write-body">
      {write.summary ? <p className="write-plan__write-summary"><RedactedText value={write.summary} /></p> : null}
      {write.fields.length ? (
        <dl className="write-plan__fields" aria-label="Fields to write">
          {write.fields.map((field, index) => (
            <div key={`${field.key}-${index}`} className="write-plan__field">
              <dt>{field.label}</dt>
              <dd><RedactedText value={field.value} /></dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="write-plan__muted">The fields follow from the writes before it.</p>
      )}
      {write.details.length ? (
        <ul className="write-plan__details" aria-label="Preview">
          {write.details.map((line, index) => (
            <li key={`${line}-${index}`}><RedactedText value={line} /></li>
          ))}
        </ul>
      ) : null}
      {write.before ? (
        <div className="write-plan__change">
          <span className="write-plan__change-label">Before</span>
          <pre><RedactedText value={write.before} /></pre>
        </div>
      ) : null}
      {write.after ? (
        <div className="write-plan__change">
          <span className="write-plan__change-label">After</span>
          <pre><RedactedText value={write.after} /></pre>
        </div>
      ) : null}
    </div>
  );
}

function WriteRow({
  write,
  number,
  open,
  onToggle,
}: {
  write: WritePlanWrite;
  number: number;
  open: boolean;
  onToggle: (open: boolean) => void;
}) {
  return (
    <li className="write-plan__write">
      <details open={open} onToggle={(event) => onToggle((event.currentTarget as HTMLDetailsElement).open)}>
        <summary className="write-plan__write-head">
          <span className="write-plan__write-number" aria-hidden="true">
            {number}
          </span>
          <span className="write-plan__write-text">
            <span className="write-plan__write-action">
              {write.action}
              {write.subject ? <span className="write-plan__write-subject"> · {write.subject}</span> : null}
            </span>
            <span className="write-plan__write-meta">
              {[write.connection ? `via ${write.connection}` : "", write.why].filter(Boolean).join(" · ")}
            </span>
          </span>
        </summary>
        <WritePlanWriteBody write={write} />
      </details>
    </li>
  );
}

export function WriteList({ writes, startOpen }: { writes: WritePlanWrite[]; startOpen: boolean }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const isOpen = (write: WritePlanWrite) => open[write.key] ?? startOpen;
  const allOpen = writes.every(isOpen);
  return (
    <section className="write-plan__writes" aria-label="Writes">
      <div className="write-plan__section-head">
        <span className="write-plan__section-label">Writes</span>
        {writes.length > 1 ? (
          <button
            type="button"
            className="ds-btn ds-btn--ghost ds-btn--sm"
            onClick={() => setOpen(Object.fromEntries(writes.map((write) => [write.key, !allOpen])))}
          >
            {allOpen ? "Collapse all" : "Expand all"}
          </button>
        ) : null}
      </div>
      <ol className="write-plan__list">
        {writes.map((write, index) => (
          <WriteRow
            key={write.key}
            write={write}
            number={index + 1}
            open={isOpen(write)}
            onToggle={(next) => setOpen((current) => (current[write.key] === next ? current : { ...current, [write.key]: next }))}
          />
        ))}
      </ol>
    </section>
  );
}

export function WritePlanCard({
  approval,
  view,
  onDecision,
  actionsDisabled = false,
  currentUserId,
}: {
  approval: ApprovalSummary;
  view: WritePlanView;
  currentUserId?: string | null;
  onDecision: (approval: ApprovalSummary, decision: ApprovalDecisionKind) => void;
  actionsDisabled?: boolean;
}) {
  const status = String(approval.status || "pending").toLowerCase();
  const result = writePlanResult(status, view, {
    approvedBy: approval.approvedBy,
    approvedByName: approval.approvedByName,
    currentUserId,
  });
  if (result) {
    return (
      <article className="message-row message-row--approval">
        <details className="write-plan write-plan--done" data-testid="write-plan" data-status={status}>
          <summary className="write-plan__result">
            <span>{result.label}</span>
            {view.request ? <span className="write-plan__result-request">{view.request}</span> : null}
          </summary>
          <div className="write-plan__done-body">
            <WritePlanScope groups={view.scope} />
            <WriteList writes={view.writes} startOpen={false} />
          </div>
        </details>
      </article>
    );
  }
  return (
    <article className="message-row message-row--approval">
      <section className="write-plan write-plan--pending" aria-label={view.heading} data-testid="write-plan" data-status={status}>
        <header className="write-plan__head">
          <div className="write-plan__heading">
            <h3 className="write-plan__title">{view.heading}</h3>
            {view.request ? (
              <p className="write-plan__request" title={view.request}>
                {view.request}
              </p>
            ) : null}
          </div>
          <StatusLabel label={view.countLabel} tone="attention" testId="write-plan-count" />
        </header>
        <WritePlanScope groups={view.scope} />
        <WriteList writes={view.writes} startOpen={!view.many} />
        {view.confirmed.length ? (
          <details className="write-plan__confirmed">
            <summary>Already confirmed · {countLabel(view.confirmed.length)}</summary>
            <ol className="write-plan__list">
              {view.confirmed.map((write, index) => (
                <WriteRow key={write.key} write={write} number={index + 1} open={false} onToggle={() => undefined} />
              ))}
            </ol>
          </details>
        ) : null}
        <footer className="write-plan__foot">
          <span className="write-plan__note">{WRITE_PLAN_NOTE}</span>
          <div className="write-plan__actions">
            <button
              type="button"
              className="ds-btn"
              disabled={actionsDisabled}
              onClick={() => onDecision(approval, "reject")}
            >
              Reject
            </button>
            <button
              type="button"
              className="ds-btn ds-btn--primary"
              disabled={actionsDisabled}
              onClick={() => onDecision(approval, "approve")}
            >
              Approve
            </button>
          </div>
        </footer>
      </section>
    </article>
  );
}
