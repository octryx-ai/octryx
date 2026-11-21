// Workspace › Data › Connectors: the side panel with one connector's access in this Workspace.
import { AdvancedSection, FormSection } from "../../../layout/FormSection";
import { SidePanel } from "../../../layout/SidePanel";
import { StatusLabel } from "../../../layout/StatusLabel";
import { ConnectorAccessLimits, ConnectorOwnConnections } from "./ProjectConnectorAccessParts";
import { connectionProduct } from "./workspaceConnectionModel";
import { inheritedSummary } from "./ProjectConnectorSettingsHelpers";
import type { ConnectorDraft, ProjectConnectorAccess } from "./ProjectConnectorSettingsHelpers";

type ReadJson = <T = unknown>(url: string, init?: RequestInit) => Promise<T>;

// Why the connector cannot run here, the save refusal and the saved note.
function ConnectorAccessMessages({ label, runtimeUnavailable, product, accessError, saved }: {
  label: string;
  runtimeUnavailable: boolean;
  product: ReturnType<typeof connectionProduct>;
  accessError: string | null;
  saved: boolean;
}) {
  return (
    <>
      {runtimeUnavailable ? (
        <div className="workspace-connection__message" data-testid="workspace-connector-runtime">
          {label} cannot run here until the platform connector is set up and on
          {product ? ", or this Workspace has its own connection" : ""}.
        </div>
      ) : null}
      {accessError ? (
        <div className="workspace-connection__message" role="alert" data-testid="connector-access-error">{accessError}</div>
      ) : null}
      {saved ? <div className="admin-panel__success" role="status">Connector access saved.</div> : null}
    </>
  );
}

// "In this Workspace": the connector on or off here.
function ConnectorUseToggle({ label, enabled, update }: { label: string; enabled: boolean; update: (patch: Partial<ConnectorDraft>) => void }) {
  return (
    <FormSection title="In this Workspace">
      <label className="admin-panel__checkbox workspace-data__toggle">
        <input
          type="checkbox"
          checked={enabled}
          data-testid="workspace-connector-enabled"
          onChange={(event) => update({ enabled: event.target.checked })}
        />
        <span>Use {label} in this Workspace</span>
      </label>
    </FormSection>
  );
}

export function ProjectConnectorAccessPanel({
  connector, projectId, readJson, draft, update, ownReady, markOwnReady, named, saving, saved, accessError, onSave, onClose,
}: {
  connector: ProjectConnectorAccess;
  projectId: string;
  readJson: ReadJson;
  draft: ConnectorDraft;
  update: (patch: Partial<ConnectorDraft>) => void;
  ownReady: boolean;
  markOwnReady: (connectorName: string, ready: boolean) => void;
  named: boolean;
  saving: boolean;
  saved: boolean;
  accessError: string | null;
  onSave: () => void;
  onClose: () => void;
}) {
  const name = connector.connector_name;
  const globalReady = connector.global_configured && connector.global_active;
  const product = connectionProduct(name);
  const runtimeUnavailable = draft.enabled && !globalReady && !ownReady;
  const state = runtimeUnavailable
    ? { label: "Global setup required", tone: "attention" as const }
    : { label: draft.enabled ? "On in this Workspace" : "Off in this Workspace", tone: "neutral" as const };

  return (
    <SidePanel
      title={connector.label}
      subtitle="Connector access in this Workspace"
      onClose={onClose}
      testId="workspace-connector-panel"
      headerActions={<StatusLabel label={state.label} tone={state.tone} testId="workspace-connector-state" />}
      footer={(
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onClose} disabled={saving}>Cancel</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" onClick={onSave}
            disabled={saving} data-testid="workspace-connector-save">
            {saving ? "Saving…" : "Save access"}
          </button>
        </>
      )}
    >
      <ConnectorAccessMessages label={connector.label} runtimeUnavailable={runtimeUnavailable} product={product} accessError={accessError} saved={saved} />

      <ConnectorUseToggle label={connector.label} enabled={draft.enabled} update={update} />

      <ConnectorAccessLimits connector={connector} projectId={projectId} readJson={readJson} draft={draft} update={update} />

      <ConnectorOwnConnections connector={connector} projectId={projectId} readJson={readJson} product={product} named={named} markOwnReady={markOwnReady} />

      <AdvancedSection label="Effective inherited limits" testId="workspace-connector-inherited">
        <pre className="workspace-data__inherited">{inheritedSummary(connector)}</pre>
      </AdvancedSection>
    </SidePanel>
  );
}
