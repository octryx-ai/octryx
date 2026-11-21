import type { ReactNode } from "react";

import { useAdminNavigation } from "../../adminNavigation";
import { DataTable } from "../../../layout/DataTable";
import { EmptyLine } from "../../../layout/EmptyLine";
import { ProjectConnectorAccessPanel } from "./ProjectConnectorAccessPanel";
import "../connectorsTab/jiraConnectorSetup.css";
import "./workspaceConnection.css";
import { namedConnector } from "../namedConnections/namedConnectionsParse";
import { useNamedDescriptors } from "../namedConnections/useNamedDescriptors";
import { WorkspaceMcpServers } from "../namedConnections/WorkspaceMcpServers";
import { WorkspaceConnectionsList } from "./WorkspaceConnectionsList";
import { WorkspaceConnectionsNarrowing } from "./WorkspaceConnectionNarrow";
import type { AvailableConnection } from "./workspaceConnectorTableState";
import type { AdminProjectQuality } from "../../types/projectQualityTypes";
import { EMPTY_DRAFT } from "./ProjectConnectorSettingsHelpers";
import type { ProjectConnectorAccess } from "./ProjectConnectorSettingsHelpers";
import { connectorAccessColumns } from "./projectConnectorAccessColumns";
import {
  connectorAccessActions,
  useAvailableConnections,
  useConnectorAccessLoad,
  useConnectorAccessState,
  type ConnectorAccessState,
} from "./useProjectConnectorAccess";
import "../adminDetailFacts.css";
import "../connectorsTab/configuredConnectorStatus.css";
import "./workspaceDataConnectors.css";

type ProjectConnectorSettingsSectionProps = {
  ctx: Record<string, unknown>;
};

type Ctx = {
  configuringProjectQuality: AdminProjectQuality | null;
  readJson: <T = unknown>(url: string, init?: RequestInit) => Promise<T>;
  CONNECTOR_COLORS?: Record<string, string>;
  CONNECTOR_ICONS?: Record<string, ReactNode>;
};

function ConnectorAccessSection({ state, available, colors, icons, openConnectorTab }: {
  state: ConnectorAccessState;
  available: AvailableConnection[];
  colors: Record<string, string>;
  icons: Record<string, ReactNode>;
  openConnectorTab: () => void;
}) {
  const { connectors, error, loaded, openName, setAccessError, setSaved, setOpenName } = state;
  return (
    <section className="workspace-data__section" aria-labelledby="workspace-connector-access-title" data-testid="workspace-connector-access">
      <div className="workspace-data__head">
        <h3 id="workspace-connector-access-title" className="workspace-data__title">Connector access</h3>
        <button type="button" className="ds-link-button" onClick={openConnectorTab}>
          Connector settings
        </button>
      </div>
      {error ? <div className="workspace-connection__message" role="alert">{error}</div> : null}
      {loaded && connectors.length === 0 ? (
        <EmptyLine text="No platform connector is set up yet." testId="workspace-connectors-empty"
          action={{ label: "Open connector settings", onClick: openConnectorTab }} />
      ) : (
        <DataTable<ProjectConnectorAccess>
          label="Connector access"
          testId="workspace-connector-table"
          loading={!loaded && !error}
          rows={connectors}
          rowKey={(connector) => connector.connector_name}
          selectedKey={openName}
          onOpen={(connector) => { setAccessError(null); setSaved(null); setOpenName(connector.connector_name); }}
          columns={connectorAccessColumns(colors, icons, available)}
        />
      )}
    </section>
  );
}

// Workspace › Data › Connectors: the connections available in this Workspace as a read-only
// list (they are managed in Admin › Connections), and what only a Workspace sets: whether it uses each platform
// connector, its own limits, its own connection and its named connections. The connectors are one compact table;
// a row opens that connector's Workspace access in the side panel, with Cancel / Save access in the footer. What
// the settings mean is in the Workspaces help (help/admin/projects.md).
export function ProjectConnectorSettingsSection({
  ctx,
}: ProjectConnectorSettingsSectionProps) {
  const { configuringProjectQuality, readJson, CONNECTOR_COLORS = {}, CONNECTOR_ICONS = {} } = ctx as Ctx;
  const project = configuringProjectQuality;
  const { openAdminTab } = useAdminNavigation();
  const state = useConnectorAccessState();
  const { connectors, drafts, saving, saved, openName, accessError, ownReady } = state;
  // The connector types with named connections (the server's descriptor registry).
  const namedRegistry = useNamedDescriptors(readJson);
  const available = useAvailableConnections(project?.id);
  const markOwnReady = useConnectorAccessLoad(state, project, readJson);
  const { updateDraft, handleSave, closePanel } = connectorAccessActions(state, project, readJson);

  if (!project) return null;
  const open = connectors.find((item) => item.connector_name === openName) ?? null;

  return (
    <div className="workspace-data" data-testid="workspace-data-connectors">
      {project.id ? <WorkspaceConnectionsList workspaceId={project.id} /> : null}
      {project.id ? <WorkspaceConnectionsNarrowing workspaceId={project.id} workspaceName={project.name} /> : null}

      <ConnectorAccessSection state={state} available={available} colors={CONNECTOR_COLORS} icons={CONNECTOR_ICONS}
        openConnectorTab={() => openAdminTab("connectors")} />

      {open && project.id && readJson ? (
        <ProjectConnectorAccessPanel
          key={open.connector_name}
          connector={open}
          projectId={project.id}
          readJson={readJson}
          draft={drafts[open.connector_name] || EMPTY_DRAFT}
          update={(patch) => updateDraft(open.connector_name, patch)}
          ownReady={Boolean(ownReady[open.connector_name])}
          markOwnReady={markOwnReady}
          named={Boolean(namedConnector(open.connector_name, namedRegistry))}
          saving={saving === open.connector_name}
          saved={saved === open.connector_name}
          accessError={accessError?.connector === open.connector_name ? accessError.text : null}
          onSave={() => void handleSave(open)}
          onClose={closePanel}
        />
      ) : null}

      {project.id && readJson ? <WorkspaceMcpServers projectId={project.id} readJson={readJson} /> : null}
    </div>
  );
}
