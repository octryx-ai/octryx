import { useEffect, useId, useRef, useState } from "react";
import { workspaceKnowledgeApi } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeApi";
import { REMOVE_SOURCE_CONSEQUENCES } from "./sourceInventoryModel";

function message(failure: unknown): string {
  return failure instanceof Error ? failure.message : String(failure);
}

// "Remove document…" inside the document drawer (authors only; the server enforces require_author and its
// refusal is shown here). An inline confirm, not a modal: Cancel keeps everything as it was.
export function KnowledgeSourceRemoval({ workspaceId, sourceId, title, onRemoved, consequences = REMOVE_SOURCE_CONSEQUENCES }: {
  workspaceId: string;
  sourceId: string;
  title: string;
  onRemoved: () => void;
  /** A synced item lists no "upload again" line. */
  consequences?: readonly string[];
}) {
  const id = useId();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  const opener = useRef<HTMLButtonElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const wasConfirming = useRef(false);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);
  useEffect(() => {
    if (confirming) cancelButton.current?.focus();
    else if (wasConfirming.current) opener.current?.focus();
    wasConfirming.current = confirming;
  }, [confirming]);
  const cancel = () => { if (!busy) { setConfirming(false); setError(null); } };
  const remove = async () => {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      await workspaceKnowledgeApi.removeSource(workspaceId, sourceId);
      if (alive.current) setBusy(false);
      onRemoved();
    } catch (failure) {
      if (alive.current) { setError(message(failure)); setBusy(false); }
    }
  };
  return <section className="knowledge-sources__remove" aria-labelledby={`${id}-label`}>
    <p id={`${id}-label`} className="user-edit-panel__section-label">Remove from this workspace</p>
    {confirming ? <div className="knowledge-sources__confirm" role="group"
      aria-labelledby={`${id}-question`} aria-busy={busy}>
      <p id={`${id}-question`} className="knowledge-sources__confirm-question">Remove “{title}”?</p>
      <ul className="knowledge-sources__confirm-list">
        {consequences.map((line) => <li key={line}>{line}</li>)}
      </ul>
      {error ? <p role="alert">{error}</p> : null}
      <div className="knowledge-sources__confirm-actions">
        <button ref={cancelButton} type="button" className="admin-panel__action-btn" disabled={busy} onClick={cancel}>
          Cancel</button>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger" disabled={busy}
          onClick={() => void remove()}>{busy ? "Removing…" : "Remove document"}</button>
      </div>
    </div> : <button ref={opener} type="button" className="admin-panel__action-btn admin-panel__action-btn--danger"
      onClick={() => setConfirming(true)}>Remove document…</button>}
  </section>;
}
