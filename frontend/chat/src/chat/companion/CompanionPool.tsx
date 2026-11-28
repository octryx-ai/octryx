import { useCallback, useEffect, useState } from "react";
import { readJson } from "../../admin/utils/adminPanelHelpers";
import { POOL_EMPTY, POOL_PATH, POOL_TAKEN, needsText, readPool, runNowText, takePath, type PoolEntry } from "./companionPoolModel";

// The panel's "Pool": the sessions of the person's Workspaces that wait for someone to take them over. Taking one is
// one atomic claim on the server; whoever is second reads its refusal here.

export function CompanionPool({ onOpenSession }: { onOpenSession?: (sessionId: string) => void }) {
  const [entries, setEntries] = useState<PoolEntry[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(() => readJson<unknown>(POOL_PATH).then((payload) => setEntries(readPool(payload)))
    .catch((error: { message?: string }) => { setEntries([]); setProblem(error?.message || "The pool could not be loaded."); }), []);
  useEffect(() => { void load(); }, [load]);

  const take = (entry: PoolEntry) => {
    setBusy(entry.id);
    setProblem(null);
    readJson<unknown>(takePath(entry.id), { method: "POST", body: JSON.stringify({}) })
      .then(() => { setNotice(POOL_TAKEN); onOpenSession?.(entry.sessionId); })
      .catch((error: { message?: string }) => setProblem(error?.message || "The session could not be taken over."))
      .finally(() => { setBusy(null); void load(); });
  };

  return (
    <section className="octryx-panel__section" aria-label="Session pool" data-testid="octryx-pool">
      {notice ? <p className="octryx-panel__hint" role="status" data-testid="octryx-pool-notice">{notice}</p> : null}
      {problem ? <p className="octryx-panel__refusal" role="alert" data-testid="octryx-pool-problem">{problem}</p> : null}
      {entries === null ? <p className="octryx-panel__hint">Loading the pool…</p> : null}
      {entries && !entries.length ? <p className="octryx-panel__hint">{POOL_EMPTY}</p> : null}
      {entries?.length ? (
        <ul className="octryx-panel__list">
          {entries.map((entry) => (
            <li key={entry.id} className="octryx-panel__item" data-testid="octryx-pool-entry">
              <strong>{entry.title}</strong>
              <span className="octryx-panel__meta">{[needsText(entry), entry.state, runNowText(entry)].filter(Boolean).join(" · ")}</span>
              {entry.summary ? <p className="octryx-panel__text">{entry.summary}</p> : null}
              <div className="octryx-panel__buttons">
                <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
                  disabled={busy !== null || !entry.canRunNow} data-testid="octryx-pool-take" onClick={() => take(entry)}>
                  {busy === entry.id ? "Taking over…" : "Take over"}
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
