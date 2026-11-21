// The global-or-own connection choice of a Workspace connector, with the confirmation before switching to global.
import { globalConnectionNote } from "./workspaceConnectionMessages";
import { type ConnectionMode, type WorkspaceConnection } from "./workspaceConnectionTypes";

type Props = {
  connectorName: string;
  label: string;
  choice: ConnectionMode;
  connection: WorkspaceConnection | null;
  storedOwn: boolean;
  confirmingGlobal: boolean;
  busy: "save" | "test" | "global" | null;
  onChooseGlobal: () => void;
  onChooseOwn: () => void;
  onUseGlobal: () => void;
  onKeepOwn: () => void;
};

export function WorkspaceConnectionChoice({ connectorName, label, choice, connection, storedOwn, confirmingGlobal, busy,
  onChooseGlobal, onChooseOwn, onUseGlobal, onKeepOwn }: Props) {
  return (
    <>
      <div
        className="connector-field jira-setup__group"
        role="radiogroup"
        aria-label={`${label} connection for this Workspace`}
      >
        <span className="connector-field__label">Connection</span>
        <div className="jira-setup__options">
          <label className="jira-setup__option">
            <input
              type="radio"
              name={`${connectorName}-connection`}
              value="global"
              checked={choice === "global"}
              onChange={onChooseGlobal}
            />
            <span className="jira-setup__option-text">
              {/* The choice's explanation is in the Workspaces help (assistive technology reads it
                  here); a state note (global connection off or not set up) stays visible. */}
              <strong>Use global connection</strong>
              <span className="ds-sr-only"> · the URL and account set in Connector settings</span>
              {globalConnectionNote(connection) ? <span>{globalConnectionNote(connection)}.</span> : <span className="ds-sr-only">.</span>}
            </span>
          </label>
          <label className="jira-setup__option">
            <input
              type="radio"
              name={`${connectorName}-connection`}
              value="own"
              checked={choice === "own"}
              onChange={onChooseOwn}
            />
            <span className="jira-setup__option-text">
              <strong>Own connection for this Workspace</strong>
              <span className="ds-sr-only"> · its own URL and account; the global one is not used here.</span>
            </span>
          </label>
        </div>
      </div>

      {confirmingGlobal && storedOwn ? (
        <div
          className="workspace-connection__confirm"
          role="note"
          data-testid="workspace-connection-confirm-global"
        >
          <span className="security-field-hint security-field-hint--attention">
            Switching to the global connection removes this Workspace&apos;s own{" "}
            {label} URL and credentials.
          </span>
          <div className="connector-card__actions">
            <button
              type="button"
              className="admin-panel__action-btn"
              disabled={busy !== null}
              onClick={onUseGlobal}
            >
              {busy === "global" ? "Switching…" : "Use global connection"}
            </button>
            <button
              type="button"
              className="admin-panel__action-btn"
              disabled={busy !== null}
              onClick={onKeepOwn}
            >
              Keep own connection
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
