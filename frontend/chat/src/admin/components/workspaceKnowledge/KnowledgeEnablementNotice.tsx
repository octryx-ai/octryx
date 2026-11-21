import { useState } from "react";
import { formatApiTime } from "./apiTime";
import {
  enableKnowledge,
  knowledgeStateOf,
  knowledgeStateText,
} from "./knowledgeEnablement";
import type { KnowledgeEnablement } from "./knowledgeEnablement";

const BADGE: Record<string, [string, string]> = {
  not_recorded: ["admin-panel__badge--warning", "not enabled"],
  needs_configuration: ["admin-panel__badge--warning", "needs configuration"],
};

// The Workspace's Knowledge state in the connectors panel, with Enable Knowledge for authors when
// it is not ready (saving a connector and Run now enable it too; this is the retry when that still fails).
// An answer without a state shows nothing until the Workspace has a connector. Ready says nothing:
// a pill without a call to action would only add noise.
export function KnowledgeEnablementNotice({
  workspaceId,
  listing,
  hasConnectors,
  mayAuthor,
  onEnabled,
}: {
  workspaceId: string;
  listing: unknown;
  hasConnectors: boolean;
  mayAuthor: boolean;
  onEnabled?: () => void;
}) {
  const [result, setResult] = useState<KnowledgeEnablement | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reported = knowledgeStateOf(listing);
  // The enable answer is newer than a listing that does not (yet) report ready.
  const shown = result && reported.state !== "ready" ? result : reported;
  // Without a connector the first-run state ("Connect your first source") is the only call to action; adding the
  // first source enables Knowledge.
  if (!hasConnectors || shown.state === "ready") return null;

  const enable = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await enableKnowledge(workspaceId));
      onEnabled?.();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };
  const [badge, label] = BADGE[shown.state] ?? [
    "admin-panel__badge--inactive",
    "not reported",
  ];
  return (
    <div
      className="admin-panel__stack admin-panel__stack--compact"
      role="status"
      data-testid="connector-knowledge-state"
      data-state={shown.state}
      style={{ margin: "0 0 0.5rem" }}
    >
      <div className="admin-panel__hint" style={{ margin: 0 }}>
        <span className={`admin-panel__badge ${badge}`}>Knowledge {label}</span>{" "}
        {knowledgeStateText(shown.state)}
        {shown.checkedAt ? ` Checked ${formatApiTime(shown.checkedAt)}.` : ""}
        {shown.outcome ? (
          <>
            {" "}
            <code>{shown.outcome}</code>
          </>
        ) : null}
        {!mayAuthor ? " A Workspace admin or owner can enable it." : null}
      </div>
      {mayAuthor ? (
        <div>
          <button
            type="button"
            className="admin-panel__action-btn"
            disabled={busy}
            onClick={() => void enable()}
          >
            {busy ? "Enabling…" : "Enable Knowledge"}
          </button>
        </div>
      ) : null}
      {error ? (
        <div className="admin-panel__error" role="alert">
          {error}
        </div>
      ) : null}
    </div>
  );
}
