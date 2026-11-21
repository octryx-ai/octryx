// A Server chat's write plan on the phone (the web's WritePlanCard and its model): the
// request, the scope as wrapping chips, the writes as compact rows that open to every field, then Reject and Approve
// at the touch height. Confirmed once, everything inside the scope runs without asking again.

import { useState } from "react";
import { StatusLabel } from "../layout/StatusLabel";
import {
  WRITE_PLAN_NOTE,
  countLabel,
  writePlanResult,
  writePlanView,
  type WritePlanDecider,
  type WritePlanView,
  type WritePlanWrite,
} from "../chat/approval/writePlanView";
import { RedactedText } from "../chat/redaction/RedactedText";
import { decideChatApproval } from "./mobileApi";
import { type MobileError } from "./mobileSession";
import { decisionErrorText } from "./phoneApprovals";

export type PendingPlan = {
  id: string;
  status: string;
  decided: boolean;
  view: WritePlanView;
  decider: WritePlanDecider;
};

const record = (value: unknown) =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

/** The chat's write plans that wait for the person, plus the ones decided on this page (shown as their result line). */
export function pendingWritePlans(
  approvals: unknown,
  decidedHere: ReadonlySet<string> = new Set(),
  currentUserId: string | null = null,
): PendingPlan[] {
  return (Array.isArray(approvals) ? approvals : []).flatMap((raw) => {
    const approval = record(raw);
    const view = writePlanView(
      record(record(approval?.changePreview)?.preview),
    );
    const status = String(approval?.status ?? "pending").toLowerCase();
    if (!approval || typeof approval.id !== "string" || !view) return [];
    const decided = Boolean(writePlanResult(status, view));
    const decider: WritePlanDecider = {
      approvedBy:
        typeof approval.approvedBy === "string" ? approval.approvedBy : null,
      approvedByName:
        typeof approval.approvedByName === "string"
          ? approval.approvedByName
          : null,
      currentUserId,
    };
    return !decided || decidedHere.has(approval.id)
      ? [{ id: approval.id, status, decided, view, decider }]
      : [];
  });
}

function Fields({ write }: { write: WritePlanWrite }) {
  return (
    <div className="m-plan-write-body">
      {write.summary && <p className="m-muted"><RedactedText value={write.summary} /></p>}
      {write.fields.length ? (
        <dl className="m-write-fields" aria-label="Fields to write">
          {write.fields.map((field, index) => (
            <div key={`${field.key}-${index}`}>
              <dt>{field.label}</dt>
              <dd><RedactedText value={field.value} /></dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="m-muted">The fields follow from the writes before it.</p>
      )}
      {write.details.length > 0 && (
        <ul className="m-plan-lines">
          {write.details.map((line, index) => (
            <li key={`${line}-${index}`}><RedactedText value={line} /></li>
          ))}
        </ul>
      )}
      {write.before && (
        <pre className="m-plan-pre"><RedactedText value={`Before\n${write.before}`} /></pre>
      )}
      {write.after && (
        <pre className="m-plan-pre"><RedactedText value={`After\n${write.after}`} /></pre>
      )}
    </div>
  );
}

export function Writes({
  writes,
  startOpen = false,
}: {
  writes: WritePlanWrite[];
  startOpen?: boolean;
}) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const isOpen = (write: WritePlanWrite) => open[write.key] ?? startOpen;
  const allOpen = writes.every(isOpen);
  return (
    <>
      {writes.length > 1 && (
        <button
          type="button"
          className="m-plan-expand"
          onClick={() =>
            setOpen(
              Object.fromEntries(writes.map((write) => [write.key, !allOpen])),
            )
          }
        >
          {allOpen ? "Collapse all" : "Expand all"}
        </button>
      )}
      <ol className="m-plan-writes">
        {writes.map((write, index) => (
          <li key={write.key}>
            <details
              open={isOpen(write)}
              onToggle={(event) => {
                const next = (event.currentTarget as HTMLDetailsElement).open;
                setOpen((current) =>
                  current[write.key] === next
                    ? current
                    : { ...current, [write.key]: next },
                );
              }}
            >
              <summary>
                <span className="m-plan-number" aria-hidden="true">
                  {index + 1}
                </span>
                <span className="m-plan-write-text">
                  <b>
                    {write.action}
                    {write.subject && (
                      <span className="m-plan-subject"> · {write.subject}</span>
                    )}
                  </b>
                  <span className="m-muted">
                    {[
                      write.connection ? `via ${write.connection}` : "",
                      write.why,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </span>
              </summary>
              <Fields write={write} />
            </details>
          </li>
        ))}
      </ol>
    </>
  );
}

/** The plan's scope as wrapping chips (the phone's approval page shows it too). */
export function PlanScope({ scope }: { scope: WritePlanView["scope"] }) {
  if (!scope.length) return null;
  return (
    <dl className="m-plan-scope" aria-label="Scope of the plan">
      {scope.map((group) => (
        <div key={group.key}>
          <dt>{group.label}</dt>
          <dd>
            {group.chips.map((chip) => (
              <span
                key={`${chip.kind}-${chip.value}`}
                className="m-plan-chip"
              >
                {chip.text}
              </span>
            ))}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function WritePlanApprovalCard({
  plan,
  onDecided,
}: {
  plan: PendingPlan;
  onDecided: (id: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { view } = plan;
  const result = writePlanResult(plan.status, view, plan.decider);
  if (result) {
    return (
      <p className="m-plan-result" data-testid="m-write-plan-result">
        {result.label}
      </p>
    );
  }
  const decide = async (decision: "approve" | "reject") => {
    setBusy(true);
    setError("");
    try {
      await decideChatApproval(plan.id, decision);
      onDecided(plan.id);
    } catch (reason) {
      const failure = reason as MobileError;
      setError(decisionErrorText(decision, failure.status, failure.detail ?? "", failure.code));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section
      className="m-write m-plan"
      aria-label={view.heading}
      data-testid="m-write-plan"
    >
      <header className="m-write-head">
        <span className="m-eyebrow">
          {view.amendment ? "Change to the plan" : "Write plan"}
        </span>
        <StatusLabel label={view.countLabel} tone="attention" />
      </header>
      <h2>{view.heading}</h2>
      {view.request && <p className="m-plan-request">{view.request}</p>}
      <PlanScope scope={view.scope} />
      <Writes writes={view.writes} startOpen={!view.many} />
      {view.confirmed.length > 0 && (
        <details className="m-plan-confirmed">
          <summary>
            Already confirmed · {countLabel(view.confirmed.length)}
          </summary>
          <Writes writes={view.confirmed} />
        </details>
      )}
      <p className="m-muted">{WRITE_PLAN_NOTE}</p>
      <div className="m-buttons">
        <button
          type="button"
          className="m-secondary"
          disabled={busy}
          onClick={() => void decide("reject")}
        >
          Reject
        </button>
        <button
          type="button"
          className="m-primary"
          disabled={busy}
          onClick={() => void decide("approve")}
        >
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
