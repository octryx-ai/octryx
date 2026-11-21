import { useRef, useState } from "react";
import { readJson } from "../chatApiClient";

type Offer = {
  id: string; state: string; payload_hash: string; round: number; state_version: number;
  acceptance: string; artefacts: Record<string, unknown>; scope: Record<string, unknown>; expires_at: string;
};
type Continuation = { state: "started" | "held"; receiver_session_id: string };
const pathOf = (id: string) => `/api/v1/workflow-handoffs/${encodeURIComponent(id)}`;

export function WorkflowHandoffButton({ handoffId }: { handoffId: string }) {
  return <HandoffPanel key={handoffId} handoffId={handoffId} />;
}

function HandoffPanel({ handoffId }: { handoffId: string }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [offer, setOffer] = useState<Offer | null>(null);
  const [server, setServer] = useState(false);
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState("");
  const [result, setResult] = useState<Continuation | "declined" | null>(null);
  const pending = useRef(false);

  async function load() {
    setOffer(null); setServer(false); setReason(""); setResult(null);
    try {
      const payload = await readJson<{ handoff: Offer }>(pathOf(handoffId));
      const current = payload.handoff;
      if (current?.id !== handoffId || !/^sha256:[a-f0-9]{64}$/.test(current.payload_hash)
          || !Number.isInteger(current.round) || current.round < 1
          || !Number.isInteger(current.state_version) || current.state_version < 1) {
        setProblem("The current handoff is unavailable."); return;
      }
      setOffer(current);
    } catch { setProblem("The current handoff is unavailable or you no longer have access."); }
  }

  async function show() {
    if (pending.current) return;
    pending.current = true; setBusy(true); setOpen(true); setProblem("");
    try { await load(); } finally { pending.current = false; setBusy(false); }
  }

  async function choose(action: "accept" | "decline") {
    if (!offer || offer.state !== "offered" || pending.current || result
        || (action === "accept" ? !server : !reason.trim())) return;
    pending.current = true; setBusy(true); setProblem("");
    const body = { action, payload_hash: offer.payload_hash, round: offer.round,
      expected_state_version: offer.state_version,
      ...(action === "accept" ? { runtime_target: { kind: "server" } } : { reason: reason.trim() }) };
    try {
      const payload = await readJson<{ handoff: { id: string; state: string; personal_response?: string };
        continuation: Continuation | null }>(`${pathOf(handoffId)}/actions`, {
        method: "POST", body: JSON.stringify(body),
      });
      if (payload.handoff?.id !== handoffId) throw new Error("Unexpected handoff response.");
      if (action === "decline" && payload.handoff.personal_response === "declined") setResult("declined");
      else if (action === "accept" && payload.handoff.state === "accepted" && payload.continuation
        && ["started", "held"].includes(payload.continuation.state) && payload.continuation.receiver_session_id) {
        setResult(payload.continuation);
      } else throw new Error("The action did not report an accepted or declined state.");
      setOffer(null);
    } catch {
      setProblem("The action was refused. Review the current offer before acting again.");
      await load();
    } finally { pending.current = false; setBusy(false); }
  }

  return <span>
    <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => void show()}>
      {busy ? "Loading…" : "Open handoff"}
    </button>
    {open ? <section aria-label="Workflow handoff" aria-live="polite">
      <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => setOpen(false)}>Close handoff</button>
      {offer ? <>
        <h3>Accept this approved handoff?</h3>
        <p>{offer.acceptance}</p>
        <p>Offer hash: <code>{offer.payload_hash}</code> · round {offer.round}</p>
        <h4>Approved artefacts</h4><pre>{JSON.stringify(offer.artefacts, null, 2)}</pre>
        <h4>Scope</h4><pre>{JSON.stringify(offer.scope, null, 2)}</pre>
        {offer.state === "offered" ? <>
          <label className="admin-panel__field">Execution target
            <select value={server ? "server" : ""} disabled={busy} onChange={event => setServer(event.target.value === "server")}>
              <option value="">Select execution target</option><option value="server">Server</option>
            </select>
          </label>
          <p>Device and Terminal selection are not yet available in this panel.</p>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy || !server} onClick={() => void choose("accept")}>Accept and initialize on Server</button>
          <label className="admin-panel__field">Why do you decline?
            <input type="text" maxLength={2000} value={reason} disabled={busy} onChange={event => setReason(event.target.value)} />
          </label>
          <button type="button" className="admin-panel__action-btn" disabled={busy || !reason.trim()} onClick={() => void choose("decline")}>Decline this round</button>
        </> : <p>This offer is no longer awaiting acceptance.</p>}
      </> : null}
      {result ? <p role="status">
        {result === "declined" ? "You declined this round." : <>
          {result.state === "started" ? "Accepted. The child workflow was initialized." : "Accepted. Child initialization is held."}
          {" "}<a href={`/chat?session_id=${encodeURIComponent(result.receiver_session_id)}`}>Open your child workflow</a>
        </>}
      </p> : null}
      {problem ? <p role="status">{problem}</p> : null}
    </section> : null}
  </span>;
}
