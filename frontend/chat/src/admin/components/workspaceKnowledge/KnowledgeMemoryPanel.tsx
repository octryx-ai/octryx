import { useCallback, useEffect, useState } from "react";
import { KnowledgeFeedbackPanel } from "./KnowledgeFeedbackPanel";
import { memoryApi } from "./memoryApi";
import type { MemoryItem, MemoryOverview } from "./memoryApi";
import { MemorySwitches, MemoryTable } from "./KnowledgeMemoryParts";

// The Workspace's memory overview, with or without history; `run` performs an action and reloads it.
function useMemoryOverview(workspaceId: string) {
  const [overview, setOverview] = useState<MemoryOverview | null>(null);
  const [history, setHistory] = useState(false);
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const run = useCallback(async (action: () => Promise<unknown>, note?: string) => {
    setBusy(true);
    try {
      await action();
      setOverview(await memoryApi.list(workspaceId, history));
      setMessage(note ?? null);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [workspaceId, history]);

  useEffect(() => {
    void run(async () => undefined);
  }, [run]);

  return { overview, history, setHistory, editing, setEditing, busy, message, run };
}

// What sessions remember for this Workspace: your personal memories and the team's. Memory is experience, not
// source evidence; the agent never cites it as a source. You can confirm, correct or forget your own memories;
// Workspace memories need the admin or owner role.
export function KnowledgeMemoryPanel({ workspaceId }: { workspaceId: string }) {
  const { overview, history, setHistory, editing, setEditing, busy, message, run } = useMemoryOverview(workspaceId);

  if (!overview) return <div className="admin-panel__hint">{message ?? "Loading…"}</div>;

  const saveCorrection = () => {
    if (!editing || !editing.text.trim()) return;
    const { id, text } = editing;
    void run(async () => {
      await memoryApi.correct(workspaceId, id, text.trim());
      setEditing(null);
    }, "Corrected. The old wording is superseded and no longer recalled.");
  };
  const forget = (item: MemoryItem) => {
    if (!window.confirm("Forget this memory? Its text, and the text of its earlier versions, is erased for good.")) return;
    void run(() => memoryApi.forget(workspaceId, item.id), "Forgotten.");
  };

  return (
    <div className="admin-panel__stack">
      <div style={{ display: "flex", alignItems: "center", gap: "0.8rem", flexWrap: "wrap" }}>
        <div className="admin-panel__hint" style={{ margin: 0, flex: "1 1 20rem" }}>
          Memories come from sessions (“remember this”). They are not source evidence: answers show them as “from
          session of …”, never as a cited source.
        </div>
        <label className="admin-panel__checkbox">
          <input type="checkbox" checked={history} onChange={(event) => setHistory(event.target.checked)} />
          Show superseded and forgotten
        </label>
      </div>

      <MemorySwitches overview={overview} workspaceId={workspaceId} busy={busy} run={run} />

      {message ? <div className="admin-panel__hint" role="status">{message}</div> : null}

      {overview.items.length ? (
        <MemoryTable items={overview.items} workspaceId={workspaceId} editing={editing} setEditing={setEditing}
          busy={busy} run={run} saveCorrection={saveCorrection} forget={forget} />
      ) : (
        <div className="admin-panel__hint" style={{ margin: 0 }}>
          Nothing is remembered in this Workspace yet. Ask the agent to “remember” a preference or a team decision.
        </div>
      )}

      {overview.may_author ? (
        <>
          <span className="admin-panel__section-title">Answer feedback</span>
          <KnowledgeFeedbackPanel workspaceId={workspaceId} />
        </>
      ) : null}
    </div>
  );
}
