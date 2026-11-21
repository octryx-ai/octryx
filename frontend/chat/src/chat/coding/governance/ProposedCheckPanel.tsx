import { useEffect, useId, useState } from "react";

import { SidePanel } from "../../../layout/SidePanel";
import { StatusLabel } from "../../../layout/StatusLabel";
import {
  approveBlocker, approveProposal, editProposal, evidenceText, kindLabel, loadProposal, proofStatus, rejectProposal,
  sourceLabel, stateStatus, switchProposal, type CheckProposal,
} from "./proposedChecksModel";

type Mode = "view" | "edit" | "reject" | "switch";
type Draft = { summary: string; what: string; why: string; instead: string };
type Act = (run: () => Promise<CheckProposal>) => Promise<void>;

// The footer's main button for the current mode: save the change, confirm the reason, or approve.
function ProposalPrimary({ formId, mode, row, busy, draft, reason, open, blocker, unproven, note, act, workspaceId }: {
  formId: string; mode: Mode; row: CheckProposal; busy: boolean; draft: Draft; reason: string; open: boolean;
  blocker: string | null; unproven: boolean; note: string; act: Act; workspaceId: string;
}) {
  return mode === "edit" ? (
    <button type="submit" form={`${formId}-edit`} className="admin-panel__action-btn admin-panel__action-btn--primary"
      disabled={busy || !draft.instead.trim()}>Save change</button>
  ) : mode === "reject" ? (
    <button type="submit" form={`${formId}-reason`} className="admin-panel__action-btn admin-panel__action-btn--primary"
      disabled={busy || !reason.trim()} data-testid="proposed-check-reject-confirm">Reject</button>
  ) : mode === "switch" ? (
    <button type="submit" form={`${formId}-reason`} className="admin-panel__action-btn admin-panel__action-btn--primary"
      disabled={busy || !reason.trim()}>{row.enabled ? "Switch off" : "Switch on"}</button>
  ) : open && !blocker ? (
    <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="proposed-check-approve"
      disabled={busy || (row.proof.state !== "proven" && (!unproven || !note.trim()))}
      onClick={() => void act(() => approveProposal(workspaceId, row.id, row.proof.state !== "proven" && unproven,
        row.proof.state !== "proven" && unproven ? note.trim() : ""))}>Approve</button>
  ) : null;
}

function ProposalFooter({ mode, setMode, open, mayApprove, row, busy, startEdit, primary }: {
  mode: Mode; setMode: (mode: Mode) => void; open: boolean; mayApprove: boolean; row: CheckProposal; busy: boolean;
  startEdit: () => void; primary: JSX.Element;
}) {
  return <>
    {mode !== "view" ? <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => setMode("view")}>Cancel</button> : null}
    {mode === "view" && open && mayApprove ? <>
      <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={startEdit} data-testid="proposed-check-edit">Change</button>
      <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => setMode("reject")} data-testid="proposed-check-reject">Reject</button>
    </> : null}
    {mode === "view" && row.state === "approved" && mayApprove ? (
      <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => setMode("switch")}>
        {row.enabled ? "Switch off" : "Switch on"}</button>
    ) : null}
    {primary}
  </>;
}

function EvidenceSection({ row }: { row: CheckProposal }) {
  return (
    <section aria-label="Evidence">
      <h3 className="proposed-check__heading">Why: {evidenceText(row)}</h3>
      <ul className="proposed-check__list">
        {(row.evidence.occurrences ?? []).map((item, index) => <li key={index}>
          <span className="admin-panel__hint">{sourceLabel(item.source)}{item.work_item_key ? ` · ${item.work_item_key}` : ""}</span>
          <q>{item.excerpt}</q>
        </li>)}
      </ul>
    </section>
  );
}

function ProposalEditForm({ formId, draft, setDraft, act, workspaceId, row }: {
  formId: string; draft: Draft; setDraft: (draft: Draft) => void; act: Act; workspaceId: string; row: CheckProposal;
}) {
  return (
    <form id={`${formId}-edit`} className="admin-panel__form" onSubmit={(event) => {
      event.preventDefault();
      void act(() => editProposal(workspaceId, row.id, { what: draft.what, why: draft.why, instead: draft.instead }, draft.summary));
    }}>
      <label className="admin-panel__field">The check<input className="admin-panel__input" value={draft.summary} maxLength={200}
        onChange={(event) => setDraft({ ...draft, summary: event.target.value })} /></label>
      <label className="admin-panel__field">What is wrong<input className="admin-panel__input" value={draft.what} maxLength={300}
        onChange={(event) => setDraft({ ...draft, what: event.target.value })} /></label>
      <label className="admin-panel__field">Why it matters<input className="admin-panel__input" value={draft.why} maxLength={500}
        onChange={(event) => setDraft({ ...draft, why: event.target.value })} /></label>
      <label className="admin-panel__field">What to do instead (required)<input className="admin-panel__input" value={draft.instead}
        maxLength={500} data-testid="proposed-check-instead" onChange={(event) => setDraft({ ...draft, instead: event.target.value })} /></label>
      <p className="admin-panel__hint">After your change a second person approves it.</p>
    </form>
  );
}

function ProofSection({ row, open, mode, blocker, unproven, setUnproven, note, setNote }: {
  row: CheckProposal; open: boolean; mode: Mode; blocker: string | null; unproven: boolean; setUnproven: (value: boolean) => void;
  note: string; setNote: (note: string) => void;
}) {
  const proof = proofStatus(row.proof);
  return (
    <section aria-label="Proof">
      <h3 className="proposed-check__heading">Proof <StatusLabel label={proof.label} tone={proof.tone} /></h3>
      <p>{proof.title}</p>
      {open && row.proof.state !== "proven" && mode === "view" && !blocker ? (
        <label className="admin-panel__checkbox"><input type="checkbox" checked={unproven} data-testid="proposed-check-unproven"
          onChange={(event) => setUnproven(event.target.checked)} /> Approve without proof</label>
      ) : null}
      {open && row.proof.state !== "proven" && mode === "view" && !blocker && unproven ? (
        <label className="admin-panel__field">Why without proof? (required, kept in the audit log)
          <input className="admin-panel__input" value={note} maxLength={500} data-testid="proposed-check-note"
            onChange={(event) => setNote(event.target.value)} /></label>
      ) : null}
    </section>
  );
}

function ReasonForm({ formId, mode, reason, setReason, act, workspaceId, row }: {
  formId: string; mode: Mode; reason: string; setReason: (reason: string) => void; act: Act; workspaceId: string; row: CheckProposal;
}) {
  return (
    <form id={`${formId}-reason`} className="admin-panel__form" onSubmit={(event) => {
      event.preventDefault();
      void act(() => (mode === "reject" ? rejectProposal(workspaceId, row.id, reason)
        : switchProposal(workspaceId, row.id, !row.enabled, reason)));
    }}>
      <label className="admin-panel__field">{mode === "reject" ? "Why not?" : "Why?"}<input className="admin-panel__input"
        value={reason} maxLength={500} data-testid="proposed-check-reason" onChange={(event) => setReason(event.target.value)} /></label>
    </form>
  );
}

function MessageSection({ row }: { row: CheckProposal }) {
  return (
    <section aria-label="Message">
      <h3 className="proposed-check__heading">The message an agent gets</h3>
      <dl className="proposed-check__facts">
        <dt>What</dt><dd>{row.message.what}</dd>
        <dt>Why</dt><dd>{row.message.why}</dd>
        <dt>Instead</dt><dd data-testid="proposed-check-message-instead">{row.message.instead}</dd>
      </dl>
    </section>
  );
}

// Where the check lands and the old instances it would flag today.
function WhereItLands({ row }: { row: CheckProposal }) {
  return (
    <>
      <section aria-label="Draft">
        <h3 className="proposed-check__heading">Where it lands</h3>
        <p>{kindLabel(row.draft.kind)} · {row.draft.rule.tool ?? "rule"}{row.draft.rule.rule_id ? ` ${row.draft.rule.rule_id}` : ""} · {row.draft.lands_in}</p>
      </section>
      <section aria-label="Old instances">
        <h3 className="proposed-check__heading">Old instances: {row.old_instances.count}</h3>
        {row.old_instances.examples.length ? <ul className="proposed-check__list">
          {row.old_instances.examples.map((item) => <li key={`${item.path}:${item.line ?? ""}`}>
            <code>{item.path}{item.line ? `:${item.line}` : ""}</code>{item.excerpt ? <> <code>{item.excerpt}</code></> : null}</li>)}
        </ul> : null}
        <p className="admin-panel__hint">It starts as a warning; it becomes an error once these are cleaned up.</p>
      </section>
    </>
  );
}

function DecisionSection({ decision }: { decision: NonNullable<CheckProposal["decision"]> }) {
  return (
    <section aria-label="Decision">
      <h3 className="proposed-check__heading">Decision</h3>
      <p>{decision.state === "approved" ? "Approved" : "Rejected"}{decision.accept_unproven ? " without proof" : ""}
        {decision.reason ? `: ${decision.reason}` : ""}</p>
    </section>
  );
}

// One proposed check: the evidence, the draft, its message with what to do instead, the old instances and the proof,
// then the decision. Four-eyes: who changed it does not approve it; approving without a proof is an explicit choice.
export function ProposedCheckPanel({ workspaceId, id, viewerId, mayApprove, onClose, onChanged }: {
  workspaceId: string; id: string; viewerId: string; mayApprove: boolean; onClose: () => void; onChanged: () => void;
}) {
  const formId = useId();
  const [row, setRow] = useState<CheckProposal | null>(null);
  const [mode, setMode] = useState<Mode>("view");
  const [draft, setDraft] = useState({ summary: "", what: "", why: "", instead: "" });
  const [reason, setReason] = useState("");
  const [unproven, setUnproven] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    void loadProposal(workspaceId, id).then((next) => { if (current) setRow(next); })
      .catch((failure: Error) => { if (current) setError(failure.message); });
    return () => { current = false; };
  }, [workspaceId, id]);

  const act = async (run: () => Promise<CheckProposal>) => {
    setBusy(true); setError(null);
    try { setRow(await run()); setMode("view"); setReason(""); onChanged(); } catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  };
  if (!row) {
    return <SidePanel title="Proposed check" onClose={onClose} testId="proposed-check-panel">
      {error ? <p role="alert">{error}</p> : <p role="status">Loading…</p>}</SidePanel>;
  }
  const shown = stateStatus(row);
  const blocker = approveBlocker(row, viewerId, mayApprove);
  const open = row.state === "proposed";
  const startEdit = () => { setDraft({ summary: row.draft.summary, ...row.message }); setMode("edit"); };
  const primary = <ProposalPrimary formId={formId} mode={mode} row={row} busy={busy} draft={draft} reason={reason} open={open}
    blocker={blocker} unproven={unproven} note={note} act={act} workspaceId={workspaceId} />;
  return <SidePanel title={row.draft.summary} subtitle={`${kindLabel(row.draft.kind)} · ${shown.label}`} onClose={onClose}
    testId="proposed-check-panel"
    footer={<ProposalFooter mode={mode} setMode={setMode} open={open} mayApprove={mayApprove} row={row} busy={busy}
      startEdit={startEdit} primary={primary} />}>
    <div className="proposed-check" data-testid="proposed-check-body">
      <EvidenceSection row={row} />
      {mode === "edit" ? (
        <ProposalEditForm formId={formId} draft={draft} setDraft={setDraft} act={act} workspaceId={workspaceId} row={row} />
      ) : (
        <MessageSection row={row} />
      )}
      <WhereItLands row={row} />
      <ProofSection row={row} open={open} mode={mode} blocker={blocker} unproven={unproven} setUnproven={setUnproven}
        note={note} setNote={setNote} />
      {row.decision ? <DecisionSection decision={row.decision} /> : null}
      {mode === "reject" || mode === "switch" ? (
        <ReasonForm formId={formId} mode={mode} reason={reason} setReason={setReason} act={act} workspaceId={workspaceId} row={row} />
      ) : null}
      {blocker && open ? <p className="admin-panel__hint" role="note" data-testid="proposed-check-blocker">{blocker}</p> : null}
      {error ? <p role="alert">{error}</p> : null}
    </div>
  </SidePanel>;
}
