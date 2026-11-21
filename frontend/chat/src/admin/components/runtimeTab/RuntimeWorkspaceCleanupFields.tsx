import { useState } from "react";
import type { ReadJsonFn } from "../../hooks/useAdminRuntimeManagement.types";
import { RuntimeField, RuntimeSettingsGroup } from "./RuntimeSettingsGroup";
import type { RuntimeTabCtx } from "./types";

type CleanupResult = { deleted: string[]; skipped: string[] };

// Behaviour source: services/session/workspace_cleanup.py cleanup_expired_session_workspaces,
// run by the session-workspace cleanup worker and by "Run cleanup now".
export function RuntimeWorkspaceCleanupFields({ ctx }: { ctx: RuntimeTabCtx }) {
  const {
    readJson,
    runtimeWorkspaceCleanupBusy,
    runtimeWorkspaceMaxAgeDraft,
    setRuntimeWorkspaceCleanupBusy,
    setRuntimeWorkspaceMaxAgeDraft,
  } = ctx;
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  const runCleanup = async () => {
    setRuntimeWorkspaceCleanupBusy(true);
    setMessage(null);
    try {
      const result = await (readJson as ReadJsonFn)<CleanupResult>(
        "/admin/chat/api/panel/runtime-workspace/cleanup",
        { method: "POST", body: JSON.stringify({}) },
      );
      const skipped = result.skipped.length ? `, ${result.skipped.length} skipped (still running)` : "";
      setMessage({ tone: "ok", text: `Deleted ${result.deleted.length} session folders${skipped}.` });
    } catch (err) {
      setMessage({
        tone: "error",
        text: err instanceof Error ? err.message : "Failed to clean runtime workspaces",
      });
    } finally {
      setRuntimeWorkspaceCleanupBusy(false);
    }
  };

  return (
    <RuntimeSettingsGroup
      title="Cleanup"
      purpose="Session folders older than the maximum age are deleted automatically; folders of running sessions are kept."
    >
      <div className="admin-form-grid">
        <RuntimeField
          id="runtime-ws-max-age"
          label="Maximum age (hours)"
          help="0 turns automatic cleanup off. Saved with the runtime settings."
        >
          <input
            id="runtime-ws-max-age"
            className="admin-panel__input"
            type="number"
            min={0}
            max={8760}
            step={1}
            value={runtimeWorkspaceMaxAgeDraft}
            onChange={(e) => setRuntimeWorkspaceMaxAgeDraft(e.target.value)}
            placeholder="24"
          />
        </RuntimeField>
        <div className="runtime-group__inline-action">
          <button
            type="button"
            className="admin-panel__action-btn"
            disabled={runtimeWorkspaceCleanupBusy}
            onClick={() => void runCleanup()}
          >
            {runtimeWorkspaceCleanupBusy ? "Cleaning…" : "Run cleanup now"}
          </button>
        </div>
      </div>
      {message ? (
        <div
          className={message.tone === "ok" ? "admin-panel__success" : "admin-panel__error"}
          role={message.tone === "ok" ? "status" : "alert"}
        >
          {message.text}
        </div>
      ) : null}
    </RuntimeSettingsGroup>
  );
}
