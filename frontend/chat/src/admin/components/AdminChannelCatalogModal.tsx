import type { ReactNode } from "react";
import { SidePanel } from "../../layout/SidePanel";
import type { AdminChannelRow } from "./channelTypes";

type AdminChannelCatalogModalProps = {
  open: boolean;
  close: () => void;
  availableChannels: AdminChannelRow[];
  search: string;
  setSearch: (value: string) => void;
  filteredAvailableChannels: AdminChannelRow[];
  getChannelIconColor: (pluginId: string) => string;
  renderChannelIcon: (pluginId: string) => ReactNode;
  onSelect: (channel: AdminChannelRow) => void;
};

export function AdminChannelCatalogModal({
  open,
  close,
  availableChannels,
  search,
  setSearch,
  filteredAvailableChannels,
  getChannelIconColor,
  renderChannelIcon,
  onSelect,
}: AdminChannelCatalogModalProps) {
  if (!open) {
    return null;
  }

  // Choosing a channel to add happens in the one side panel over the list.
  return (
    <SidePanel title="Add channel" onClose={close} testId="channel-catalog-panel"
      footer={(
        <button type="button" className="admin-panel__action-btn" onClick={close}>
          Cancel
        </button>
      )}
    >
          {availableChannels.length === 0 ? (
            <div className="admin-panel__empty-state">
              No channel templates are available.
            </div>
          ) : (
            <>
              <label className="thread-search thread-search--inline">
                <svg viewBox="0 0 20 20" aria-hidden="true">
                  <circle cx="9" cy="9" r="5.5" />
                  <path d="M13.2 13.2 17 17" />
                </svg>
                <input
                  type="search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search channels"
                  aria-label="Search channels"
                />
              </label>
              {filteredAvailableChannels.length === 0 ? (
                <div className="admin-panel__empty-state">
                  No channels match your search.
                </div>
              ) : (
                <div className="admin-option-list">
                  {filteredAvailableChannels.map((channel) => (
                    <button
                      key={`${channel.plugin_id}-${channel.name}`}
                      type="button"
                      className="admin-option-card"
                      onClick={() => onSelect(channel)}
                    >
                      <div
                        className="admin-option-card__icon"
                        style={{
                          color: getChannelIconColor(channel.plugin_id),
                        }}
                      >
                        {renderChannelIcon(channel.plugin_id)}
                      </div>
                      <div className="admin-option-card__body">
                        <div className="admin-option-card__title">
                          {channel.name}
                        </div>
                        {channel.description ? (
                          <div className="admin-option-card__desc">
                            {channel.description}
                          </div>
                        ) : null}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
    </SidePanel>
  );
}
