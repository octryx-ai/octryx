import { useEffect, useState } from "react";
import { loadHandoverCandidates, requestHandover } from "./companionApi";
import { POOLED_TEXT, TO_POOL, handoverRequestedText, type HandoverCandidate } from "./companionHandoverModel";
import type { JobDetail } from "./companionJobModel";

// "Hand over…" inside a job's detail: choose who takes the run over (or the session pool) and say why. The run keeps working until the
// receiver accepts; the receiver answers in their own companion. The server checks that the receiver is a member of
// the run's Workspace and shows its refusal here in its own words.

export function CompanionHandover({ job, title, onClose, onRequested }: {
  job: JobDetail; title: string; onClose: () => void; onRequested: (text: string) => void;
}) {
  const [candidates, setCandidates] = useState<HandoverCandidate[] | null>(null);
  const [toUserId, setToUserId] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    loadHandoverCandidates(job.workspace?.id ?? "", job.owner?.id ?? "").then((next) => {
      if (current) setCandidates(next);
    }).catch(() => {
      if (current) { setCandidates([]); setProblem("The people of this Workspace could not be loaded."); }
    });
    return () => { current = false; };
  }, [job.owner?.id, job.workspace?.id]);

  const missing = !toUserId ? "Choose who takes the run over." : !reason.trim() ? "Enter a reason to continue." : null;
  const submit = () => {
    if (missing) { setProblem(missing); return; }
    setBusy(true);
    setProblem(null);
    const name = candidates?.find((candidate) => candidate.id === toUserId)?.name || "them";
    requestHandover(job.runId, toUserId, reason)
      .then(() => onRequested(toUserId === TO_POOL ? POOLED_TEXT : handoverRequestedText(name)))
      .catch((error: { message?: string }) => setProblem(error?.message || "The handover could not be requested."))
      .finally(() => setBusy(false));
  };

  return (
    <form className="octryx-handover" aria-label={`Hand over "${title}"`} data-testid="octryx-handover"
      onSubmit={(event) => { event.preventDefault(); submit(); }}>
      <label className="admin-panel__field">
        <span>Hand over to</span>
        <select className="admin-panel__input" value={toUserId} disabled={busy || !candidates} data-testid="octryx-handover-to"
          onChange={(event) => setToUserId(event.target.value)}>
          <option value="">{candidates ? "Choose a person" : "Loading people…"}</option>
          {(candidates ?? []).map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.name}</option>)}
          {candidates ? <option value={TO_POOL}>The session pool (whoever can run it now)</option> : null}
        </select>
      </label>
      {candidates && !candidates.length ? (
        <p className="octryx-panel__hint">No one else is a member of this Workspace: the session pool waits for one.</p>
      ) : null}
      <label className="admin-panel__field">
        <span>Reason (required)</span>
        <input type="text" className="admin-panel__input" value={reason} disabled={busy} data-testid="octryx-handover-reason"
          placeholder="e.g. I am away tomorrow, please finish the review" onChange={(event) => setReason(event.target.value)} />
      </label>
      <div className="octryx-panel__buttons">
        <button type="submit" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy || Boolean(missing)}
          data-testid="octryx-handover-send">
          {busy ? "Sending…" : "Request handover"}
        </button>
        <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={onClose}>Cancel</button>
      </div>
      {/* Why the button waits, below it: the button itself always says what it does. */}
      {missing && !problem ? <p className="octryx-panel__hint" data-testid="octryx-handover-why">{missing}</p> : null}
      {problem ? <p className="octryx-panel__refusal" role="alert" data-testid="octryx-handover-problem">{problem}</p> : null}
    </form>
  );
}
