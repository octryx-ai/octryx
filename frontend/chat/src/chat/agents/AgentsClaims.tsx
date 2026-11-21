import { useCallback, useEffect, useState } from "react";

import { formatRelativeTime } from "../../admin/utils/formatters";
import { requestActionNeededRefresh } from "./actionNeededRefresh";
import { handOverNow, loadClaims, releaseClaim } from "./agentBoardApi";
import { BOARD_POLL_MS, boardActionErrorText, boardLoadErrorText, readClaims, readViewer, workItemHref } from "./agentBoardModel";
import { leaseText } from "./agentBoardLabels";
import type { BoardClaim } from "./agentBoardTypes";
import { useVisiblePolling } from "./useVisiblePolling";

// The "Claims and handoffs" view: the Workspace's active work claims with holder, lease countdown
// and declared paths. When the answer's `viewer.can_admin` is true (D-F1), a stale claim may be released after an
// in-page confirmation; the server authorizes it.
// Pending takeovers and the structured handoffs are the next subsection (AgentsHandoffs).
export function AgentsClaims({ projectId, pollMs = BOARD_POLL_MS }: { projectId: string; pollMs?: number }) {
  const [claims, setClaims] = useState<{ projectId: string; items: BoardClaim[]; canAdmin: boolean } | null>(null);
  const [problem, setProblem] = useState<{ projectId: string; text: string } | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  // Freeze 3c: "Hand over now" has its own in-page confirmation.
  const [handoverId, setHandoverId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<{ ok: boolean; text: string } | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback((isCurrent: () => boolean) => {
    void loadClaims(projectId).then((payload) => {
      if (!isCurrent()) return;
      const items = readClaims(payload);
      if (items === null) setProblem({ projectId, text: "The server's answer was not a list of claims." });
      else { setProblem(null); setClaims({ projectId, items, canAdmin: readViewer(payload)?.canAdmin === true }); }
    }).catch((error) => {
      if (isCurrent()) setProblem({ projectId, text: boardLoadErrorText(error, "claims") });
    });
  }, [projectId]);
  useVisiblePolling(load, projectId, pollMs);

  // The lease countdown ticks once a second.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const handOver = async (claim: BoardClaim) => {
    setBusy(true);
    setOutcome(null);
    try {
      const answer = await handOverNow(claim.id) as { session_asked?: unknown } | null;
      const item = claim.workItem?.key || "the work item";
      setOutcome({ ok: true, text: answer?.session_asked === true
        ? `Handoff requested for ${item}: the holder's agent hands its work over at its next step.`
        : `Handoff requested for ${item}: the request is posted; the holder is not a launcher session, so its work state is not collected automatically.` });
      setHandoverId(null);
      load(() => true);
      requestActionNeededRefresh();
    } catch (error) {
      setOutcome({ ok: false, text: boardActionErrorText(error) });
    } finally {
      setBusy(false);
    }
  };

  const release = async (claim: BoardClaim) => {
    setBusy(true);
    setOutcome(null);
    try {
      await releaseClaim(claim.id);
      setOutcome({ ok: true, text: `The claim on ${claim.workItem?.key || "the work item"} was released.` });
      setConfirmId(null);
      load(() => true);
      requestActionNeededRefresh();
    } catch (error) {
      setOutcome({ ok: false, text: boardActionErrorText(error) });
    } finally {
      setBusy(false);
    }
  };

  const items = claims?.projectId === projectId ? claims.items : null;
  const isAdmin = claims?.projectId === projectId && claims.canAdmin;
  return (
    <section className="admin-panel__card agents-board" aria-label="Claims and handoffs" data-testid="agents-claims">
      <div className="admin-panel__section-header"><h2 className="agents-area__section-title">Claims</h2></div>
      <p className="agents-area__hint">Active work claims. Takeover requests wait below for a confirmation; their board posts are on the message board.</p>
      {outcome ? <p className={outcome.ok ? "agents-area__hint" : "work-area__error"} role={outcome.ok ? "status" : "alert"}
        data-testid="agents-claims-outcome">{outcome.text}</p> : null}
      {problem?.projectId === projectId ? <p className="work-area__error" role="alert" data-testid="agents-claims-error">{problem.text}</p>
        : items === null ? <p className="agents-area__hint" role="status">Loading the claims…</p>
          : !items.length ? <p className="admin-panel__empty-state" data-testid="agents-claims-empty">No work item is claimed in this Workspace.</p>
            : (
              <div className="work-table-wrap">
                <table className="work-table" data-testid="agents-claims-table">
                  <thead><tr><th>Work item</th><th>Holder</th><th>Lease</th><th>Paths</th><th>Claimed</th>{isAdmin ? <th>Admin</th> : null}</tr></thead>
                  <tbody>
                    {items.map((claim) => (
                      <tr key={claim.id} data-testid="agents-claim-row">
                        <td>{claim.workItem ? (
                          <a href={workItemHref(projectId, claim.workItem.id)}><strong>{claim.workItem.key}</strong>{claim.workItem.title ? <span> {claim.workItem.title}</span> : null}</a>
                        ) : "—"}</td>
                        <td>{claim.holder ? `Agent of ${claim.holder.name}` : "Unknown agent"}{claim.epoch !== null ? <span className="agents-area__hint"> · epoch {claim.epoch}</span> : null}</td>
                        <td data-testid="agents-claim-lease">{leaseText(claim.leaseUntil, now)}</td>
                        <td>{claim.paths.length ? claim.paths.map((entry) => <code key={entry} className="agents-board__path">{entry}</code>) : "—"}</td>
                        <td>{formatRelativeTime(claim.claimedAt) || "—"}</td>
                        {isAdmin ? (
                          <td>
                            {confirmId === claim.id ? (
                              <span className="agents-board__confirm" role="group" aria-label="Confirm release">
                                Release this claim? The agent's next write gets "claim lost".
                                <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => setConfirmId(null)}>Cancel</button>
                                <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger" disabled={busy} onClick={() => void release(claim)}>Release now</button>
                              </span>
                            ) : handoverId === claim.id ? (
                              <span className="agents-board__confirm" role="group" aria-label="Confirm hand over now">
                                Ask {claim.holder ? `the agent of ${claim.holder.name}` : "the holding agent"} to hand its work over now? It posts a handoff request with the latest handoff; the work state follows at the agent's next step.
                                <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => setHandoverId(null)}>Cancel</button>
                                <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy} onClick={() => void handOver(claim)}>Request handoff now</button>
                              </span>
                            ) : (
                              <span className="agents-table-actions">
                                <button type="button" className="admin-panel__action-btn" onClick={() => { setOutcome(null); setConfirmId(null); setHandoverId(claim.id); }}>Hand over now</button>
                                <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger" onClick={() => { setOutcome(null); setConfirmId(claim.id); }}>Release</button>
                              </span>
                            )}
                          </td>
                        ) : null}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
    </section>
  );
}
