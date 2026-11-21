import type { Dispatch, SetStateAction } from "react";
import type { MCPCatalogEntry } from "./mcpTypes";
import { SidePanel } from "../../layout/SidePanel";
import { isMcpSecretField } from "./mcpWorkspaceContract";

type AdminMcpInstallModalProps = {
  selectedPreset: MCPCatalogEntry | null;
  editingServerName: string | null;
  workspaceName: string;
  close: () => void;
  mcpInstallName: string;
  setMcpInstallName: Dispatch<SetStateAction<string>>;
  mcpInstallValues: Record<string, string>;
  setMcpInstallValues: Dispatch<SetStateAction<Record<string, string>>>;
  mcpInstallAutoStart: boolean;
  setMcpInstallAutoStart: Dispatch<SetStateAction<boolean>>;
  mcpInstallError: string | null;
  mcpInstallLoading: boolean;
  handleInstallMcpCatalog: () => Promise<void>;
};

export function AdminMcpInstallModal({
  selectedPreset,
  editingServerName,
  workspaceName,
  close,
  mcpInstallName,
  setMcpInstallName,
  mcpInstallValues,
  setMcpInstallValues,
  mcpInstallAutoStart,
  setMcpInstallAutoStart,
  mcpInstallError,
  mcpInstallLoading,
  handleInstallMcpCatalog,
}: AdminMcpInstallModalProps) {
  if (!selectedPreset) {
    return null;
  }
  const isEditing = Boolean(editingServerName);

  // Install and edit of a preset in the one side panel: Cancel, then the primary action.
  return (
    <SidePanel
      title={`${isEditing ? "Edit" : "Install"} ${selectedPreset.name}`}
      subtitle={`Workspace ${workspaceName}`}
      onClose={close}
      testId="mcp-install-panel"
      footer={(
        <InstallFooter isEditing={isEditing} loading={mcpInstallLoading} close={close} onInstall={() => void handleInstallMcpCatalog()} />
      )}
    >
          <div className="admin-modal__stack">
            <div className="admin-panel__hint">
              {selectedPreset.description}
            </div>
            {isEditing ? null : (
              <div className="admin-panel__hint">New registrations start inactive.</div>
            )}

            <ServerNameField value={mcpInstallName} setValue={setMcpInstallName} disabled={isEditing}
              placeholder={selectedPreset.default_name} />

            {selectedPreset.fields.map((field) => (
              <PresetField key={field.name} field={field} isEditing={isEditing} values={mcpInstallValues} setValues={setMcpInstallValues} />
            ))}

            <AutoStartToggle on={mcpInstallAutoStart} setOn={setMcpInstallAutoStart} />
            {mcpInstallError ? (
              <div className="admin-panel__error">{mcpInstallError}</div>
            ) : null}
          </div>
    </SidePanel>
  );
}

function InstallFooter({
  isEditing,
  loading,
  close,
  onInstall,
}: {
  isEditing: boolean;
  loading: boolean;
  close: () => void;
  onInstall: () => void;
}) {
  return (
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
        disabled={loading}
        onClick={onInstall}
      >
        {loading
          ? isEditing
            ? "Saving…"
            : "Installing…"
          : isEditing
            ? "Save"
            : "Install"}
      </button>
    </>
  );
}

function PresetField({
  field,
  isEditing,
  values,
  setValues,
}: {
  field: MCPCatalogEntry["fields"][number];
  isEditing: boolean;
  values: Record<string, string>;
  setValues: Dispatch<SetStateAction<Record<string, string>>>;
}) {
  const value = values[field.name] ?? String(field.default || "");
  const update = (next: string) => setValues((current) => ({ ...current, [field.name]: next }));
  const secret = isMcpSecretField(field);
  return (
    <div className="admin-form-field">
      <label className="admin-form-field__label">
        {field.label}
        {secret ? " (Secret Reference)" : null}
        {field.required ? (
          <span className="admin-form-field__required">*</span>
        ) : null}
      </label>
      {field.type === "select" ? (
        <select className="admin-panel__form-input" value={value} onChange={(event) => update(event.target.value)}>
          {(field.options || []).map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      ) : (
        <input
          className="admin-panel__form-input"
          type="text"
          value={value}
          onChange={(event) => update(event.target.value)}
          placeholder={secret ? "secret:<id>" : field.placeholder || ""}
          autoComplete="off"
        />
      )}
      {secret ? (
        <div className="admin-form-help">
          {isEditing
            ? "Leave blank to keep the bound Secret Reference, or enter another one to rebind it."
            : "Enter the Secret Reference of a stored secret, never the raw value."}
        </div>
      ) : null}
    </div>
  );
}

function AutoStartToggle({ on, setOn }: { on: boolean; setOn: Dispatch<SetStateAction<boolean>> }) {
  return (
    <label className="admin-form-toggle-row">
      <div className="admin-form-toggle-copy">
        <strong>Auto-start</strong>
        <div className="admin-form-help">
          Connect automatically when the backend starts and try to
          activate immediately after install.
        </div>
      </div>
      <span
        className={`toggle-switch ${on ? "toggle-switch--on" : ""}`}
        onClick={() => setOn((value) => !value)}
        role="switch"
        aria-checked={on}
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === " " || event.key === "Enter") {
            setOn((value) => !value);
          }
        }}
      />
    </label>
  );
}

function ServerNameField({
  value,
  setValue,
  disabled,
  placeholder,
}: {
  value: string;
  setValue: Dispatch<SetStateAction<string>>;
  disabled: boolean;
  placeholder: string;
}) {
  return (
    <div className="admin-form-field">
      <label className="admin-form-field__label">
        Server name{" "}
        <span className="admin-form-field__required">*</span>
      </label>
      <input
        className="admin-panel__form-input"
        type="text"
        value={value}
        disabled={disabled}
        onChange={(event) => setValue(event.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}
