import { useCallback, useEffect, useState } from "react";

import { formatRelativeTime } from "../../admin/utils/formatters";
import { requestActionNeededRefresh } from "./actionNeededRefresh";
import { confirmTakeover, declineTakeover, loadClaims, loadHandoffs, loadTakeovers } from "./agentBoardApi";
import { boardActionErrorText, boardLoadErrorText, readClaims, readViewer } from "./agentBoardModel";
import type { BoardViewer, BoardWorkItem } from "./agentBoardTypes";
import { HANDOFF_POLL_MS, TAKEOVER_STATUS_LABEL, decisionLabel, expiryText, mayDecideTakeover, handsToAgent, partyLabel, snapshotLines } from "./agentHandoffView";
import { readHandoffs, readTakeovers } from "./agentHandoffModel";
import type { Handoff, Takeover } from "./agentHandoffTypes";
import { AgentsHandoffViewer } from "./AgentsHandoffViewer";
import { useVisiblePolling } from "./useVisiblePolling";

type Listing = { projectId: string; takeovers: Takeover[]; recent: Takeover[]; handoffs: Handoff[]; viewer: BoardViewer | null };

// "Handoffs and takeovers" in Agents → Claims and handoffs. Pending takeovers show who asks,
// the item, the reason and the expiry; the receiving user or an admin confirms or declines in the page (D1 refined:
// never only through the agent), each after an in-page confirmation. Every item's structured handoff opens in the
// viewer. Polls every 10 s while visible.
export function AgentsHandoffs({ projectId, focusTakeoverId = null, focusWorkItemId = null, focusClaimId = null, pollMs = HANDOFF_POLL_MS }: {
  projectId: string;
  focusTakeoverId?: string | null;
  focusWorkItemId?: string | null;
  // An `available_handoff` notification link names the holder's claim; its work item's handoff opens.
  focusClaimId?: string | null;
  pollMs?: number;
}) {
  const [listing, setListing] = useState<Listing | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [open, setOpen] = useState<{ workItem: BoardWorkItem; version: number | null } | null>(null);
  const [focusOpened, setFocusOpened] = useState(false);
  // A decided takeover leaves the pending list on the next load, so its outcome is kept here, not in its card.
  const [decided, setDecided] = useState<string | null>(null);

  const load = useCallback((isCurrent: () => boolean) => {
    // Confirmed takeovers (freeze 3b: automatic ones read "Handed over automatically") load alongside; when they cannot
    // be loaded the pending ones still show.
    void Promise.all([
      loadTakeovers(projectId, "pending"), loadHandoffs(projectId), loadTakeovers(projectId, "confirmed").catch(() => null),
      // judge-s4 F2: a takeover whose claim changed before a decision is cancelled; it is listed with the reason.
      loadTakeovers(projectId, "cancelled").catch(() => null),
    ]).then(([takeoverPayload, handoffPayload, confirmedPayload, cancelledPayload]) => {
      if (!isCurrent()) return;
      // The status is checked here too, so each list holds only its own status whatever the server sends.
      const takeovers = readTakeovers(takeoverPayload)?.filter((entry) => entry.status === "pending") ?? null;
      const recent = [
        ...(readTakeovers(confirmedPayload) ?? []).filter((entry) => entry.status === "confirmed"),
        ...(readTakeovers(cancelledPayload) ?? []).filter((entry) => entry.status === "cancelled"),
      ].sort((a, b) => (b.decidedAt ?? b.createdAt ?? "").localeCompare(a.decidedAt ?? a.createdAt ?? ""));
      const handoffs = readHandoffs(handoffPayload);
      if (takeovers === null || handoffs === null) {
        setProblem("The server's answer was not a list of takeovers and handoffs.");
        return;
      }
      setProblem(null);
      setListing({ projectId, takeovers, recent, handoffs, viewer: readViewer(takeoverPayload) ?? readViewer(handoffPayload) });
    }).catch((error) => {
      if (isCurrent()) setProblem(boardLoadErrorText(error, "takeovers and handoffs"));
    });
  }, [projectId]);
  useVisiblePolling(load, projectId, pollMs);

  const current = listing?.projectId === projectId ? listing : null;
  useEffect(() => {
    if (!focusClaimId) return undefined;
    let live = true;
    loadClaims(projectId).then((payload) => {
      const workItem = (readClaims(payload) ?? []).find((claim) => claim.id === focusClaimId)?.workItem;
      if (live && workItem) setOpen({ workItem, version: null });
    }).catch(() => undefined);
    return () => { live = false; };
  }, [projectId, focusClaimId]);
  // A bell or notification link to an item opens its handoff once, as soon as the item is known.
  useEffect(() => {
    if (!current || !focusWorkItemId || focusOpened) return;
    const known = current.handoffs.find((entry) => entry.workItem?.id === focusWorkItemId)?.workItem
      ?? current.takeovers.find((entry) => entry.workItem?.id === focusWorkItemId)?.workItem;
    setFocusOpened(true);
    if (known) setOpen({ workItem: known, version: null });
  }, [current, focusWorkItemId, focusOpened]);

  return (
    <section className="admin-panel__card agents-board" aria-label="Handoffs and takeovers" data-testid="agents-handoffs">
      <div className="admin-panel__section-header"><h2 className="agents-area__section-title">Handoffs and takeovers</h2></div>
      {decided ? <p className="agents-area__hint" role="status" data-testid="agents-takeover-decided">{decided}</p> : null}
      {problem ? <p className="work-area__error" role="alert" data-testid="agents-handoffs-error">{problem}</p>
        : !current ? <p className="agents-area__hint" role="status">Loading takeovers and handoffs…</p>
          : (
            <>
              {current.takeovers.length ? current.takeovers.map((takeover) => (
                <TakeoverCard key={takeover.id} takeover={takeover} viewer={current.viewer} focused={takeover.id === focusTakeoverId}
                  onDecided={(textValue) => { setDecided(textValue); load(() => true); }}
                  onOpenHandoff={(workItem, version) => setOpen({ workItem, version })} />
              )) : <p className="admin-panel__empty-state" data-testid="agents-takeovers-empty">No takeover is waiting for a confirmation.</p>}
              {current.recent.length ? (
                <div className="agents-board" data-testid="agents-recent-takeovers">
                  <h3 className="agents-area__subsection-title">Recent takeovers</h3>
                  {current.recent.map((takeover) => (
                    <article key={takeover.id} data-testid="agents-recent-takeover" data-takeover-id={takeover.id}
                      className={`admin-panel__subcard agents-board__message${takeover.id === focusTakeoverId ? " is-focused" : ""}`}>
                      <header className="agents-board__meta">
                        <span className={`work-badge work-badge--${takeover.status === "cancelled" ? "neutral" : takeover.decidedBy?.kind === "system" ? "attention" : "active"}`}
                          data-testid="agents-recent-decision">{decisionLabel(takeover) || TAKEOVER_STATUS_LABEL[takeover.status]}</span>
                        <strong>{takeover.workItem?.key || "Work item"}: from {partyLabel(takeover.from)} to {partyLabel(takeover.to)}</strong>
                        <span className="agents-board__time">{formatRelativeTime(takeover.decidedAt) || ""}</span>
                      </header>
                      {takeover.decidedBy?.kind === "system" ? (
                        <ul className="agents-handoff-policy__snapshot" data-testid="agents-recent-snapshot">
                          {snapshotLines(takeover).map((line) => <li key={line}>{line}</li>)}
                        </ul>
                      ) : null}
                    </article>
                  ))}
                </div>
              ) : null}
              {current.handoffs.length ? (
                <div className="work-table-wrap">
                  <table className="work-table" data-testid="agents-handoffs-table">
                    <thead><tr><th>Work item</th><th>Latest version</th><th>Written by</th><th>When</th><th /></tr></thead>
                    <tbody>
                      {current.handoffs.map((handoff) => (
                        <tr key={handoff.id} data-testid="agents-handoff-row">
                          <td>{handoff.workItem ? <><strong>{handoff.workItem.key}</strong>{handoff.workItem.title ? <span> {handoff.workItem.title}</span> : null}</> : "—"}</td>
                          <td>v{handoff.version ?? "?"}</td>
                          <td>{handoff.author ? (handoff.authorType === "human" ? handoff.author.name : `Agent of ${handoff.author.name}`) : "—"}</td>
                          <td>{formatRelativeTime(handoff.createdAt) || "—"}</td>
                          <td>{handoff.workItem ? (
                            <button type="button" className="admin-panel__action-btn"
                              onClick={() => handoff.workItem && setOpen({ workItem: handoff.workItem, version: null })}>Open handoff</button>
                          ) : null}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <p className="admin-panel__empty-state" data-testid="agents-handoffs-empty">No handoff has been written in this Workspace yet.</p>}
            </>
          )}
      {open ? (
        <AgentsHandoffViewer key={`${open.workItem.id}|${open.version ?? "latest"}`} projectId={projectId}
          workItem={open.workItem} version={open.version} onClose={() => setOpen(null)} />
      ) : null}
    </section>
  );
}

function TakeoverCard({ takeover, viewer, focused, onDecided, onOpenHandoff }: {
  takeover: Takeover;
  viewer: BoardViewer | null;
  focused: boolean;
  onDecided: (outcome: string) => void;
  onOpenHandoff: (workItem: BoardWorkItem, version: number | null) => void;
}) {
  const [confirming, setConfirming] = useState<"confirm" | "decline" | null>(null);
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const item = takeover.workItem;
  const itemLabel = item?.key || item?.title || "the work item";
  const canDecide = mayDecideTakeover(takeover, viewer);

  const decide = async (action: "confirm" | "decline") => {
    setBusy(true);
    setRefusal(null);
    try {
      await (action === "confirm" ? confirmTakeover(takeover.id) : declineTakeover(takeover.id));
      setConfirming(null);
      onDecided(action === "confirm"
        ? handsToAgent(takeover)
          ? `Confirmed: ${partyLabel(takeover.to)} now holds ${itemLabel}.`
          : `Confirmed: the claim on ${itemLabel} is released; ${partyLabel(takeover.to)}'s agent claims it next.`
        : `Declined: ${partyLabel(takeover.from)} keeps ${itemLabel}.`);
      requestActionNeededRefresh();
    } catch (error) {
      setRefusal(boardActionErrorText(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className={`admin-panel__subcard agents-board__message${focused ? " is-focused" : ""}`} data-testid="agents-takeover" data-takeover-id={takeover.id}>
      <header className="agents-board__meta">
        <span className="work-badge work-badge--attention">{TAKEOVER_STATUS_LABEL[takeover.status]}</span>
        <strong data-testid="agents-takeover-summary">Takeover of {itemLabel}: from {partyLabel(takeover.from)} to {partyLabel(takeover.to)}</strong>
        <span className="agents-board__time" data-testid="agents-takeover-expiry">{expiryText(takeover.expiresAt)}</span>
      </header>
      {takeover.reason ? <p className="agents-board__body" data-testid="agents-takeover-reason">{takeover.reason}</p> : null}
      <footer className="agents-board__meta agents-board__footer">
        {item ? (
          <button type="button" className="admin-panel__action-btn" onClick={() => onOpenHandoff(item, takeover.handoff?.version ?? null)}>
            {takeover.handoff ? `Read handoff v${takeover.handoff.version ?? "?"}` : "Read handoff"}
          </button>
        ) : null}
        {canDecide && !confirming ? (
          <>
            <button type="button" className="admin-panel__action-btn" onClick={() => { setRefusal(null); setConfirming("decline"); }}>Decline</button>
            <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" onClick={() => { setRefusal(null); setConfirming("confirm"); }}>Confirm takeover</button>
          </>
        ) : null}
        {confirming ? (
          <span className="agents-board__confirm" role="group" aria-label={confirming === "confirm" ? "Confirm takeover" : "Confirm decline"}>
            {confirming === "confirm"
              ? handsToAgent(takeover)
                ? `Move the claim on ${itemLabel} to ${partyLabel(takeover.to)}? The current holder's next write gets "claim lost".`
                : `Release the claim on ${itemLabel} so ${partyLabel(takeover.to)}'s agent can claim it? The current holder's next write gets "claim lost".`
              : `Decline? ${partyLabel(takeover.from)} keeps ${itemLabel}.`}
            <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => setConfirming(null)}>Cancel</button>
            <button type="button" className={`admin-panel__action-btn ${confirming === "confirm" ? "admin-panel__action-btn--primary" : "admin-panel__action-btn--danger"}`}
              disabled={busy} onClick={() => void decide(confirming)}>
              {confirming === "confirm" ? "Confirm now" : "Decline now"}
            </button>
          </span>
        ) : null}
      </footer>
      {refusal ? <p className="work-area__error" role="alert" data-testid="agents-takeover-refusal">{refusal}</p> : null}
    </article>
  );
}
