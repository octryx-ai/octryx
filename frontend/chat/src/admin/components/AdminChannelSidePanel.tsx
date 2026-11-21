// Channels tab: the side panel of one channel (facts, Reload, Enable/Disable, Configure, Remove in the menu).
import { AdminDetailFacts } from "./AdminDetailFacts";
import { channelState } from "./AdminChannelCardList";
import { SidePanel } from "../../layout/SidePanel";
import { StatusLabel } from "../../layout/StatusLabel";
import { ActionMenu } from "./workflowSurfaces/ActionMenu";
import type { AdminChannelRow, AdminChannelsTabProps } from "./channelTypes";

type AdminChannelSidePanelProps = {
  openChannel: AdminChannelRow;
  closeChannelPanel: () => void;
  removeChannel: (channel: AdminChannelRow) => Promise<void>;
  reloadChannel: (channel: AdminChannelRow) => Promise<void>;
  updateChannelEnabled: (channel: AdminChannelRow, enabled: boolean) => Promise<void>;
  openChannelConfig: (channel: AdminChannelRow) => void;
  formatRelativeTime: AdminChannelsTabProps["formatRelativeTime"];
};

export function AdminChannelSidePanel({
  openChannel, closeChannelPanel, removeChannel, reloadChannel, updateChannelEnabled, openChannelConfig, formatRelativeTime,
}: AdminChannelSidePanelProps) {
  return (
    <SidePanel
      title={openChannel.name}
      subtitle={`Channel · ${openChannel.plugin_id}`}
      onClose={closeChannelPanel}
      testId="channel-panel"
      // Remove sits in the ⋯ menu at the top: a menu in the footer would open below the screen.
      headerActions={(
        <ActionMenu
          row={{ objectName: openChannel.name }}
          items={[
            {
              label: "Remove…",
              danger: true,
              onSelect: () => void removeChannel(openChannel),
            },
          ]}
        />
      )}
      footer={(
        <>
          <button
            type="button"
            className="admin-panel__action-btn"
            onClick={() => void reloadChannel(openChannel)}
          >
            Reload
          </button>
          <button
            type="button"
            className="admin-panel__action-btn"
            onClick={() =>
              void updateChannelEnabled(openChannel, !openChannel.enabled)
            }
          >
            {openChannel.enabled ? "Disable" : "Enable"}
          </button>
          <button
            type="button"
            className="admin-panel__action-btn admin-panel__action-btn--primary"
            onClick={() => {
              closeChannelPanel();
              openChannelConfig(openChannel);
            }}
          >
            Configure
          </button>
        </>
      )}
    >
      <AdminDetailFacts
        testId="channel-facts"
        facts={[
          {
            label: "State",
            value: <StatusLabel label={channelState(openChannel)} tone="neutral" />,
          },
          { label: "Type", value: openChannel.plugin_id },
          { label: "Workspace", value: openChannel.project_name || "No Workspace" },
          { label: "Description", value: openChannel.description },
          { label: "Webhook", value: openChannel.webhook_url },
          {
            label: "Updated",
            value: openChannel.updated_at
              ? formatRelativeTime(openChannel.updated_at)
              : "Not updated yet",
          },
        ]}
      />
    </SidePanel>
  );
}
