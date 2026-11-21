// Admin call agents tab: Workspace call agent table with a side panel to read, edit, test-run or delete.
import { DataTable } from "../../layout/DataTable";
import { EmptyLine } from "../../layout/EmptyLine";
import { SidePanel } from "../../layout/SidePanel";
import { WorkspaceScopeSelect } from "./WorkspaceScopeSelect";
import { AdminCallAgentForm } from "./AdminCallAgentForm";
import type { CallAgentConfig } from "./callAgentTypes";
import { useCallAgentsTab, type CallAgentsTabState } from "./useCallAgentsTab";

type CallAgentsTabProps = {
  projects: Array<{ id: string; name: string }>;
};

export function AdminCallAgentsTab({ projects }: CallAgentsTabProps) {
  const tab = useCallAgentsTab();
  const { selectedProjectId, setSelectedProjectId, configs, error } = tab.data;

  // Voice calls: the call agents of a Workspace as a table; a row or "New call agent" opens the
  // one side panel, where the agent is read, edited, test-run or deleted.
  return (
    <div className="admin-call-agents">
      <div className="admin-panel__section-header">
        <span>Call agents ({configs.length})</span>
        {selectedProjectId ? (
          <button type="button" className="admin-panel__action-btn" onClick={tab.handleNewConfig} data-testid="call-agent-new">
            New call agent
          </button>
        ) : null}
      </div>
      <WorkspaceScopeSelect projects={projects} value={selectedProjectId} onChange={setSelectedProjectId} />

      {error && !tab.panelOpen ? <p className="admin-panel__error" role="alert">{error}</p> : null}

      {selectedProjectId ? (
        <CallAgentsTable tab={tab} />
      ) : (
        <EmptyLine text="Select a Workspace to manage its call agents." testId="call-agents-select-workspace" />
      )}

      {tab.panelOpen ? <CallAgentPanel tab={tab} /> : null}
    </div>
  );
}

function CallAgentsTable({ tab }: { tab: CallAgentsTabState }) {
  const { configs, loading, selectedConfig } = tab.data;
  return (
    <DataTable<CallAgentConfig>
      label="Call agents"
      testId="call-agents-table"
      loading={loading && configs.length === 0}
      rows={configs}
      rowKey={(config) => config.id}
      selectedKey={selectedConfig?.id ?? null}
      onOpen={tab.handleSelectConfig}
      empty={{ text: "No call agents in this Workspace yet.", action: { label: "New call agent", onClick: tab.handleNewConfig } }}
      columns={[
        { key: "name", header: "Name", grow: true, render: (config) => config.name },
        { key: "model", header: "Model", nowrap: true, render: (config) => config.llm_model },
        { key: "channel", header: "Channel", nowrap: true, render: (config) => tab.channelLabel(config.channel_id) },
      ]}
    />
  );
}

function CallAgentPanelFooter({ tab }: { tab: CallAgentsTabState }) {
  const { selectedConfig } = tab.data;
  return tab.form.isEditing ? (
    <>
      <button type="button" className="admin-panel__action-btn" onClick={selectedConfig ? tab.cancelEdit : tab.closePanel}>
        Cancel
      </button>
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" onClick={() => void tab.handleSave()}>
        Save
      </button>
    </>
  ) : (
    <>
      <button type="button" className="admin-panel__danger-btn"
        onClick={() => selectedConfig && void tab.handleDelete(selectedConfig.id)}>
        Delete
      </button>
      <button type="button" className="admin-panel__action-btn" onClick={() => void tab.handleTestRun()}>
        Test run
      </button>
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" onClick={() => tab.form.setIsEditing(true)}>
        Edit
      </button>
    </>
  );
}

function CallAgentPanel({ tab }: { tab: CallAgentsTabState }) {
  const { selectedConfig, error, availableChannels, runtimeModels } = tab.data;
  return (
    <SidePanel
      title={selectedConfig ? selectedConfig.name : "New call agent"}
      subtitle="Call agent"
      onClose={tab.closePanel}
      testId="call-agent-panel"
      footer={<CallAgentPanelFooter tab={tab} />}
    >
      {error ? <p className="admin-panel__error" role="alert">{error}</p> : null}
      <AdminCallAgentForm
        fields={tab.form}
        isEditing={tab.form.isEditing}
        availableChannels={availableChannels}
        runtimeModels={runtimeModels}
      />
    </SidePanel>
  );
}
