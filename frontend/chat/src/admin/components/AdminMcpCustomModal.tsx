import type { Dispatch, SetStateAction } from "react";
import { MCP_CUSTOM_TRANSPORTS } from "./mcpWorkspaceContract";
import { SidePanel } from "../../layout/SidePanel";

type AdminMcpCustomModalProps = {
  open: boolean;
  workspaceName: string;
  close: () => void;
  customMcpName: string;
  setCustomMcpName: Dispatch<SetStateAction<string>>;
  customMcpTransport: string;
  setCustomMcpTransport: Dispatch<SetStateAction<string>>;
  customMcpUrl: string;
  setCustomMcpUrl: Dispatch<SetStateAction<string>>;
  customMcpDescription: string;
  setCustomMcpDescription: Dispatch<SetStateAction<string>>;
  customMcpAutoStart: boolean;
  setCustomMcpAutoStart: Dispatch<SetStateAction<boolean>>;
  customMcpLoading: boolean;
  customMcpError: string | null;
  onCreate: () => Promise<void>;
};

type FieldsProps = Pick<AdminMcpCustomModalProps,
  "customMcpName" | "setCustomMcpName" | "customMcpTransport" | "setCustomMcpTransport" | "customMcpUrl" | "setCustomMcpUrl" |
  "customMcpDescription" | "setCustomMcpDescription">;

function McpCustomFields({
  customMcpName, setCustomMcpName, customMcpTransport, setCustomMcpTransport, customMcpUrl, setCustomMcpUrl,
  customMcpDescription, setCustomMcpDescription,
}: FieldsProps) {
  return (
    <>
      <div className="admin-form-field">
        <label className="admin-form-field__label">
          Name <span className="admin-form-field__required">*</span>
        </label>
        <input
          className="admin-panel__form-input"
          type="text"
          value={customMcpName}
          onChange={(event) => setCustomMcpName(event.target.value)}
        />
      </div>
      <div className="admin-form-field">
        <label className="admin-form-field__label">Transport</label>
        <select
          className="admin-panel__form-input"
          value={customMcpTransport}
          onChange={(event) => setCustomMcpTransport(event.target.value)}
        >
          {MCP_CUSTOM_TRANSPORTS.map((transport) => (
            <option key={transport} value={transport}>
              {transport}
            </option>
          ))}
        </select>
      </div>
      <div className="admin-form-field">
        <label className="admin-form-field__label">
          URL <span className="admin-form-field__required">*</span>
        </label>
        <input
          className="admin-panel__form-input"
          type="text"
          value={customMcpUrl}
          onChange={(event) => setCustomMcpUrl(event.target.value)}
        />
      </div>
      <div className="admin-form-field">
        <label className="admin-form-field__label">Description</label>
        <input
          className="admin-panel__form-input"
          type="text"
          value={customMcpDescription}
          onChange={(event) =>
            setCustomMcpDescription(event.target.value)
          }
        />
      </div>
    </>
  );
}

function McpAutoStartToggle({ customMcpAutoStart, setCustomMcpAutoStart }: Pick<AdminMcpCustomModalProps, "customMcpAutoStart" | "setCustomMcpAutoStart">) {
  return (
    <label className="admin-form-toggle-row">
      <div className="admin-form-toggle-copy">
        <strong>Auto-start</strong>
        <div className="admin-form-help">
          Attempt to connect automatically when the backend starts.
        </div>
      </div>
      <span
        className={`toggle-switch ${customMcpAutoStart ? "toggle-switch--on" : ""}`}
        onClick={() => setCustomMcpAutoStart((value) => !value)}
        role="switch"
        aria-checked={customMcpAutoStart}
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === " " || event.key === "Enter") {
            setCustomMcpAutoStart((value) => !value);
          }
        }}
      />
    </label>
  );
}

export function AdminMcpCustomModal(props: AdminMcpCustomModalProps) {
  const { open, workspaceName, close, customMcpLoading, customMcpError, onCreate } = props;
  if (!open) {
    return null;
  }

  // Registering a custom server in the one side panel: Cancel, then the primary action.
  return (
    <SidePanel
      title="Add custom MCP"
      subtitle={`Workspace ${workspaceName}`}
      onClose={close}
      testId="mcp-custom-panel"
      footer={(
        <>
          <button
            type="button"
            className="admin-panel__action-btn"
            onClick={close}
          >
            Cancel
          </button>
          <button
            type="button"
            className="admin-panel__action-btn admin-panel__action-btn--primary"
            disabled={customMcpLoading}
            onClick={() => void onCreate()}
          >
            {customMcpLoading ? "Saving…" : "Create MCP"}
          </button>
        </>
      )}
    >
          <div className="admin-modal__stack">
            <div className="admin-panel__hint">New registrations start inactive.</div>
            <McpCustomFields {...props} />
            <McpAutoStartToggle {...props} />
            {customMcpError ? (
              <div className="admin-panel__error">{customMcpError}</div>
            ) : null}
          </div>
    </SidePanel>
  );
}
