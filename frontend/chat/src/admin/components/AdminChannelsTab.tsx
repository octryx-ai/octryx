import { Suspense, lazy, useState } from "react";
import {
  AdminChannelCardList,
  channelKey,
} from "./AdminChannelCardList";
import { AdminChannelCatalogModal } from "./AdminChannelCatalogModal";
import {
  AdminChannelSectionTabs,
  type AdminChannelSection,
} from "./AdminChannelSectionTabs";
import { AdminChannelConfigModal } from "./AdminChannelConfigModal";
import { AdminChannelDeliveryLogPanel } from "./AdminChannelDeliveryLogPanel";
import { AdminChannelDeliveryTargetsPanel } from "./AdminChannelDeliveryTargetsPanel";
import { AdminCallSessionsSection } from "./AdminCallSessionsSection";
import { AdminProblemAlertsSection } from "./AdminProblemAlertsSection";
import { AdminChannelSessionsTable } from "./AdminChannelSessionsTable";
import type { AdminChannelsTabProps } from "./channelTypes";
import { LoadingState } from "../../layout/LoadingState";
import { AdminHeaderActions } from "./AdminHeaderSlot";
import { adminChannelActions } from "./adminChannelActions";
import { AdminChannelSidePanel } from "./AdminChannelSidePanel";


const AdminCallAgentsTab = lazy(async () => {
  const module = await import("./AdminCallAgentsTab");
  return { default: module.AdminCallAgentsTab };
});

type AdminChannelsTabWrapperProps = {
  ctx: Record<string, unknown>;
};

export function AdminChannelsTab({ ctx }: AdminChannelsTabWrapperProps) {
  const props = ctx as AdminChannelsTabProps;
  const { channels, channelSessions, channelDeliveryLogs, projects, availableLoading, formatRelativeTime } = props;
  const actions = adminChannelActions(props);
  const { openAddChannel } = actions;

  const [channelSection, setChannelSection] = useState<AdminChannelSection>("overview");
  // The channel whose side panel is open; it follows the reloaded list by key.
  const [openChannelKey, setOpenChannelKey] = useState<string | null>(null);
  const openChannel = channels.find((channel) => channelKey(channel) === openChannelKey) ?? null;
  const closeChannelPanel = () => setOpenChannelKey(null);
  const teamsConfigured = channels.some((channel) => channel.plugin_id === "msteams" && channel.id != null);
  const setUpChannel = () => {
    setChannelSection("overview");
    void openAddChannel();
  };

  return (
    <div>
      <AdminHeaderActions>
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={openAddChannel}
          disabled={availableLoading}
          data-testid="channel-add"
        >
          {availableLoading ? "Loading…" : "Add channel"}
        </button>
      </AdminHeaderActions>
      <AdminChannelSectionTabs value={channelSection} onChange={setChannelSection} />

      {channelSection === "voice" ? (
        <Suspense fallback={<LoadingState label="voice settings" variant="page" />}>
          <AdminCallAgentsTab projects={projects} />
        </Suspense>
      ) : null}

      {channelSection === "overview" ? (
        <ChannelsOverview props={props} actions={actions} openChannelKey={openChannelKey} setOpenChannelKey={setOpenChannelKey}
          openChannel={openChannel} closeChannelPanel={closeChannelPanel} setUpChannel={setUpChannel} />
      ) : null}

      {channelSection === "alerts" ? <AdminProblemAlertsSection channels={channels} projects={projects} /> : null}

      {channelSection === "outbound" ? (
        <AdminChannelDeliveryLogPanel logs={channelDeliveryLogs} channels={channels} projects={projects}
          formatRelativeTime={formatRelativeTime} onSetUpChannel={setUpChannel} />
      ) : null}

      {channelSection === "sessions" ? (
        <ChannelSessions sessions={channelSessions} formatRelativeTime={formatRelativeTime} hasChannels={channels.length > 0}
          teamsConfigured={teamsConfigured} setUpChannel={setUpChannel} />
      ) : null}

      <ChannelModals props={props} actions={actions} />
    </div>
  );
}

type ChannelActions = ReturnType<typeof adminChannelActions>;

function ChannelsOverview({
  props,
  actions,
  openChannelKey,
  setOpenChannelKey,
  openChannel,
  closeChannelPanel,
  setUpChannel,
}: {
  props: AdminChannelsTabProps;
  actions: ChannelActions;
  openChannelKey: string | null;
  setOpenChannelKey: (key: string | null) => void;
  openChannel: AdminChannelsTabProps["channels"][number] | null;
  closeChannelPanel: () => void;
  setUpChannel: () => void;
}) {
  const { channels, getChannelIconColor, renderChannelIcon, formatRelativeTime } = props;
  const { openAddChannel, openChannelConfig, updateChannelEnabled, reloadChannel, removeChannel } = actions;
  return (
    <>
      <AdminChannelCardList
        channels={channels}
        getChannelIconColor={getChannelIconColor}
        renderChannelIcon={renderChannelIcon}
        formatRelativeTime={formatRelativeTime}
        onToggleEnabled={updateChannelEnabled}
        onConfigure={openChannelConfig}
        onReload={reloadChannel}
        onRemove={removeChannel}
        onAdd={openAddChannel}
        onOpen={(channel) => setOpenChannelKey(channelKey(channel))}
        selectedKey={openChannelKey}
      />

      <DeliveryTargets props={props} actions={actions} setUpChannel={setUpChannel} />

      {openChannel ? (
        <AdminChannelSidePanel openChannel={openChannel} closeChannelPanel={closeChannelPanel} removeChannel={removeChannel}
          reloadChannel={reloadChannel} updateChannelEnabled={updateChannelEnabled} openChannelConfig={openChannelConfig}
          formatRelativeTime={formatRelativeTime} />
      ) : null}
    </>
  );
}

function ChannelSessions({
  sessions,
  formatRelativeTime,
  hasChannels,
  teamsConfigured,
  setUpChannel,
}: {
  sessions: AdminChannelsTabProps["channelSessions"];
  formatRelativeTime: AdminChannelsTabProps["formatRelativeTime"];
  hasChannels: boolean;
  teamsConfigured: boolean;
  setUpChannel: () => void;
}) {
  return (
    <>
      <div className="admin-panel__section-header">
        <span>Channel sessions ({sessions.length})</span>
      </div>
      <AdminChannelSessionsTable
        sessions={sessions}
        formatRelativeTime={formatRelativeTime}
        hasChannels={hasChannels}
        onSetUpChannel={setUpChannel}
      />
      <AdminCallSessionsSection
        teamsConfigured={teamsConfigured}
        onSetUpChannel={setUpChannel}
      />
    </>
  );
}

function ChannelModals({ props, actions }: { props: AdminChannelsTabProps; actions: ChannelActions }) {
  const {
    projects, showAddChannel, availableChannels, channelCatalogSearch, setChannelCatalogSearch, filteredAvailableChannels,
    configuringChannel, channelFormName, setChannelFormName, channelFormProjectId, setChannelFormProjectId, channelFormEnabled,
    setChannelFormEnabled, channelConfigJson, setChannelConfigJson, channelFormValues, setChannelFormValues, channelShowRawJson,
    setChannelShowRawJson, channelFormLoading, channelFormError, getChannelIconColor, renderChannelIcon,
  } = props;
  const { closeAddChannel, closeChannelConfig, selectChannelTemplate, saveChannel } = actions;
  return (
    <>
      <AdminChannelCatalogModal
        open={showAddChannel}
        close={closeAddChannel}
        availableChannels={availableChannels}
        search={channelCatalogSearch}
        setSearch={setChannelCatalogSearch}
        filteredAvailableChannels={filteredAvailableChannels}
        getChannelIconColor={getChannelIconColor}
        renderChannelIcon={renderChannelIcon}
        onSelect={selectChannelTemplate}
      />

      <AdminChannelConfigModal
        channel={configuringChannel}
        onClose={closeChannelConfig}
        projects={projects}
        channelFormName={channelFormName}
        setChannelFormName={setChannelFormName}
        channelFormProjectId={channelFormProjectId}
        setChannelFormProjectId={setChannelFormProjectId}
        channelFormEnabled={channelFormEnabled}
        setChannelFormEnabled={setChannelFormEnabled}
        channelShowRawJson={channelShowRawJson}
        setChannelShowRawJson={setChannelShowRawJson}
        channelConfigJson={channelConfigJson}
        setChannelConfigJson={setChannelConfigJson}
        channelFormValues={channelFormValues}
        setChannelFormValues={setChannelFormValues}
        channelFormError={channelFormError}
        channelFormLoading={channelFormLoading}
        onSave={saveChannel}
      />
    </>
  );
}

function DeliveryTargets({ props, actions, setUpChannel }: { props: AdminChannelsTabProps; actions: ChannelActions; setUpChannel: () => void }) {
  const {
    channels, channelDeliveryTargets, channelDeliveryProjectId, setChannelDeliveryProjectId, channelDeliveryEventType,
    setChannelDeliveryEventType, channelDeliveryChannelId, setChannelDeliveryChannelId, channelDeliveryTarget,
    setChannelDeliveryTarget, channelDeliveryLoading, channelDeliveryError, projects,
  } = props;
  const { createDeliveryTarget, deleteDeliveryTarget } = actions;
  return (
    <AdminChannelDeliveryTargetsPanel
      channels={channels}
      projects={projects}
      targets={channelDeliveryTargets}
      projectId={channelDeliveryProjectId}
      setProjectId={setChannelDeliveryProjectId}
      eventType={channelDeliveryEventType}
      setEventType={setChannelDeliveryEventType}
      channelId={channelDeliveryChannelId}
      setChannelId={setChannelDeliveryChannelId}
      target={channelDeliveryTarget}
      setTarget={setChannelDeliveryTarget}
      loading={channelDeliveryLoading}
      error={channelDeliveryError}
      onCreate={createDeliveryTarget}
      onDelete={deleteDeliveryTarget}
      onSetUpChannel={setUpChannel}
    />
  );
}
