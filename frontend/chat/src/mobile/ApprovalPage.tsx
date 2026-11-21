// One approval on the phone (backend): what is asked, in the web's own preview models (REST request, write plan,
// connector write, generic), who asked, where and when, then Deny (with an optional short reason) and Allow once, as far
// as the server offers them. "Always for this Workspace" stays in the web. The outcome reads in words.

import { useState } from "react";
import { StatusLabel, type StatusTone } from "../layout/StatusLabel";
import { WRITE_PLAN_NOTE } from "../chat/approval/writePlanView";
import { RedactedText } from "../chat/redaction/RedactedText";
import { Icon } from "./icons";
import { decideApproval } from "./mobileApi";
import { type MobileError } from "./mobileSession";
import { shortTime } from "./mobileUsageModel";
import { DetailHeader } from "./PageHeader";
import {
  REASON_CHARS,
  approvalMeta,
  decisionErrorText,
  decisionOutcome,
  phoneApprovalLink,
  settledByRefusal,
  type PhoneApproval,
  type PhoneDecision,
} from "./phoneApprovals";
import { PhonePreview } from "./ApprovalPreview";

type Props = {
  approval: PhoneApproval;
  workspace: string;
  onBack: () => void;
  // The list is read again after a decision or a refusal that settles it.
  onSettled: () => void;
  onOpenRun: (runId: string, title: string) => void;
  onOpenChat: (sessionId: string, title: string) => void;
};

type Outcome = { decision: PhoneDecision; text: string } | null;

function approvalStatus(approval: PhoneApproval, outcome: Outcome, settled: boolean): { label: string; tone: StatusTone } {
  const write = approval.preview === "plan" || approval.preview === "connector";
  const decided = outcome?.decision === "approve" ? (write ? "Approved" : "Allowed once") : write ? "Rejected" : "Denied";
  return outcome
    ? { label: decided, tone: outcome.decision === "approve" ? "neutral" : "problem" }
    : settled
      ? { label: "Not waiting", tone: "neutral" }
      : { label: "Waiting for you", tone: "attention" };
}

function DenyForm({ reason, setReason, busy, setDenying, decide }: {
  reason: string;
  setReason: (reason: string) => void;
  busy: boolean;
  setDenying: (denying: boolean) => void;
  decide: (decision: PhoneDecision) => Promise<void>;
}) {
  return (
    <form
      className="m-approval-deny"
      onSubmit={(event) => {
        event.preventDefault();
        void decide("reject");
      }}
    >
      <label className="m-field">
        <span>Reason (optional)</span>
        <textarea
          value={reason}
          maxLength={REASON_CHARS}
          rows={2}
          placeholder="Why not, in a few words"
          data-testid="m-approval-reason"
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <div className="m-buttons">
        <button type="button" className="m-secondary" disabled={busy} onClick={() => setDenying(false)}>
          Cancel
        </button>
        <button type="submit" className="m-danger" disabled={busy} data-testid="m-approval-deny-confirm">
          Deny
        </button>
      </div>
    </form>
  );
}

function DecisionButtons({ approval, busy, setDenying, decide }: {
  approval: PhoneApproval;
  busy: boolean;
  setDenying: (denying: boolean) => void;
  decide: (decision: PhoneDecision) => Promise<void>;
}) {
  const deny = approval.decisions.find((item) => item.kind === "reject");
  const allow = approval.decisions.find((item) => item.kind === "approve");
  return (
    <>
      <p className="m-muted">
        {approval.preview === "plan" ? WRITE_PLAN_NOTE : "Only this request. The next one asks again."}
      </p>
      <div className="m-buttons">
        {deny && (
          <button
            type="button"
            className={`m-secondary${allow ? "" : " m-wide"}`}
            disabled={busy}
            data-testid="m-approval-reject"
            onClick={() => setDenying(true)}
          >
            {deny.label}
          </button>
        )}
        {allow && (
          <button
            type="button"
            className={`m-primary${deny ? "" : " m-wide"}`}
            disabled={busy}
            data-testid="m-approval-approve"
            onClick={() => void decide("approve")}
          >
            {allow.label}
          </button>
        )}
      </div>
    </>
  );
}

// The outcome once decided; else nothing when settled elsewhere, the read-only note, the deny form or the buttons.
function ApprovalDecisions({ approval, outcome, settled, denying, setDenying, reason, setReason, busy, decide }: {
  approval: PhoneApproval;
  outcome: Outcome;
  settled: boolean;
  denying: boolean;
  setDenying: (denying: boolean) => void;
  reason: string;
  setReason: (reason: string) => void;
  busy: boolean;
  decide: (decision: PhoneDecision) => Promise<void>;
}) {
  return outcome ? (
    <p className="m-plan-result" role="status" data-testid="m-approval-outcome">
      {outcome.text}
    </p>
  ) : settled ? null : approval.decisions.length === 0 ? (
    <p className="m-muted" data-testid="m-approval-readonly">
      {approval.governance
        ? "A governance review is decided on its publishing page in the web app."
        : "This approval is decided in the web app."}
    </p>
  ) : denying ? (
    <DenyForm reason={reason} setReason={setReason} busy={busy} setDenying={setDenying} decide={decide} />
  ) : (
    <DecisionButtons approval={approval} busy={busy} setDenying={setDenying} decide={decide} />
  );
}

// Sends the decision; a refusal that settles the approval elsewhere hides the buttons and reads the list again.
async function decideOnPhone(ctx: {
  approval: PhoneApproval;
  reason: string;
  onSettled: () => void;
  setBusy: (busy: boolean) => void;
  setError: (error: string) => void;
  setOutcome: (outcome: Outcome) => void;
  setSettled: (settled: boolean) => void;
}, decision: PhoneDecision) {
  const { approval, reason, onSettled, setBusy, setError, setOutcome, setSettled } = ctx;
  setBusy(true);
  setError("");
  try {
    await decideApproval(approval.id, decision, decision === "reject" ? reason : "");
    setOutcome({ decision, text: decisionOutcome(decision, decision === "reject" ? reason : "", approval.preview) });
    onSettled();
  } catch (failure) {
    const refused = failure as MobileError;
    const status = typeof refused.status === "number" ? refused.status : 0;
    setError(decisionErrorText(decision, status, refused.detail ?? "", refused.code));
    if (settledByRefusal(status)) {
      setSettled(true);
      onSettled();
    }
  } finally {
    setBusy(false);
  }
}

export function ApprovalPage({ approval, workspace, onBack, onSettled, onOpenRun, onOpenChat }: Props) {
  const [busy, setBusy] = useState(false);
  const [denying, setDenying] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [outcome, setOutcome] = useState<{ decision: PhoneDecision; text: string } | null>(null);
  // Refused because it is not waiting for this person any more (decided elsewhere, gone, out of reach): no buttons.
  const [settled, setSettled] = useState(false);
  const link = phoneApprovalLink(approval);
  const meta = approvalMeta({
    workspace,
    requestedBy: approval.requestedByName ?? "",
    ago: shortTime(approval.createdAt),
  });

  const decide = (decision: PhoneDecision) =>
    decideOnPhone({ approval, reason, onSettled, setBusy, setError, setOutcome, setSettled }, decision);
  const status = approvalStatus(approval, outcome, settled);

  return (
    <div className="m-screen">
      <DetailHeader title="Approval" subtitle={workspace || undefined} onBack={onBack} />
      <main className="m-body">
        <section className="m-write m-approval" aria-label={`Approval: ${approval.title}`} data-testid="m-approval">
          <header className="m-write-head">
            <span className="m-eyebrow">Octryx asks first</span>
            <StatusLabel label={status.label} tone={status.tone} testId="m-approval-status" />
          </header>
          <h2 className="m-approval-title"><RedactedText value={approval.title} /></h2>
          {approval.subtitle && (
            <p className="m-approval-subtitle" data-testid="m-approval-subtitle"><RedactedText value={approval.subtitle} /></p>
          )}
          {meta && <p className="m-muted">{meta}</p>}
          {link && (
            <button
              type="button"
              className="m-approval-link"
              data-testid="m-approval-link"
              onClick={() =>
                link.kind === "run" ? onOpenRun(link.runId, approval.title) : onOpenChat(link.sessionId, approval.title)
              }
            >
              <span>{link.kind === "run" ? "Open the run" : "Open the chat"}</span>
              <Icon name="chevronRight" size={18} className="m-row-chevron" />
            </button>
          )}
          <PhonePreview approval={approval} />
          <ApprovalDecisions approval={approval} outcome={outcome} settled={settled} denying={denying}
            setDenying={setDenying} reason={reason} setReason={setReason} busy={busy} decide={decide} />
          {error && (
            <p className="m-error" role="alert" data-testid="m-approval-error">
              {error}
            </p>
          )}
        </section>
      </main>
    </div>
  );
}
