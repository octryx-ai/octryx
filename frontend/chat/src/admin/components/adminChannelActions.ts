// Channels tab actions: open the catalog and the config form, save, enable, reload or remove a channel, and manage
// delivery targets.
import type { AdminChannelDeliveryTargetRow, AdminChannelRow, AdminChannelsTabProps as Props } from "./channelTypes";

function buildDefaultConfig(channel: AdminChannelRow): Record<string, unknown> {
  const defaultConfig: Record<string, unknown> = {};
  for (const field of channel.config_fields) {
    if (field.default !== undefined) {
      defaultConfig[field.name] = field.default;
      continue;
    }
    if (field.type === "boolean") {
      defaultConfig[field.name] = false;
    } else if (field.type === "number") {
      defaultConfig[field.name] = 0;
    } else {
      defaultConfig[field.name] = "";
    }
  }
  return defaultConfig;
}

async function openAddChannel(p: Props) {
  p.setAvailableLoading(true);
  try {
    const data = await p.readJson<AdminChannelRow[]>(
      "/admin/chat/api/panel/channels/available",
    );
    p.setAvailableChannels(data);
    p.setChannelCatalogSearch("");
    p.setShowAddChannel(true);
  } catch (err) {
    alert(
      err instanceof Error
        ? err.message
        : "Failed to load available channels",
    );
  } finally {
    p.setAvailableLoading(false);
  }
}

function closeAddChannel(p: Props) {
  p.setShowAddChannel(false);
}

function openChannelConfig(p: Props, channel: AdminChannelRow) {
  p.setConfiguringChannel(channel);
  p.setChannelFormName(channel.name);
  p.setChannelFormProjectId(channel.project_id || "");
  p.setChannelFormEnabled(channel.enabled);
  p.setChannelConfigJson(JSON.stringify(channel.config, null, 2));
  p.setChannelFormValues(channel.config);
  p.setChannelShowRawJson(false);
  p.setChannelFormError(null);
}

function closeChannelConfig(p: Props) {
  p.setConfiguringChannel(null);
}

function selectChannelTemplate(p: Props, channel: AdminChannelRow) {
  const defaultConfig = buildDefaultConfig(channel);
  p.setShowAddChannel(false);
  p.setChannelCatalogSearch("");
  p.setConfiguringChannel({
    ...channel,
    id: null,
    enabled: false,
    config: defaultConfig,
    status: "stopped",
    updated_at: null,
  });
  p.setChannelFormName(channel.name);
  p.setChannelFormProjectId("");
  p.setChannelFormEnabled(false);
  p.setChannelConfigJson(JSON.stringify(defaultConfig, null, 2));
  p.setChannelFormValues(defaultConfig);
  p.setChannelShowRawJson(false);
  p.setChannelFormError(null);
}

async function updateChannelEnabled(p: Props, channel: AdminChannelRow, enabled: boolean) {
  try {
    await p.readJson(`/admin/chat/api/panel/channels/${channel.id}`, {
      method: "PUT",
      body: JSON.stringify({
        name: channel.name,
        project_id: channel.project_id,
        enabled,
        config: channel.config,
      }),
    });
    p.reloadChannelsTab();
  } catch (err) {
    alert(err instanceof Error ? err.message : "Failed to update channel");
  }
}

async function reloadChannel(p: Props, channel: AdminChannelRow) {
  try {
    await p.readJson(`/admin/chat/api/panel/channels/${channel.id}/reload`, {
      method: "POST",
    });
    p.reloadChannelsTab();
  } catch (err) {
    alert(err instanceof Error ? err.message : "Reload failed");
  }
}

async function createDeliveryTarget(p: Props): Promise<boolean> {
  p.setChannelDeliveryLoading(true);
  p.setChannelDeliveryError(null);
  try {
    const created = await p.readJson<AdminChannelDeliveryTargetRow>(
      "/admin/chat/api/panel/channel-delivery-targets",
      {
        method: "POST",
        body: JSON.stringify({
          project_id: p.channelDeliveryProjectId,
          event_type: p.channelDeliveryEventType,
          channel_type: "teams",
          channel_config_id: p.channelDeliveryChannelId
            ? Number(p.channelDeliveryChannelId)
            : null,
          target: p.channelDeliveryTarget,
          is_active: true,
        }),
      },
    );
    p.setChannelDeliveryTargets((prev) => [created, ...prev]);
    p.setChannelDeliveryTarget("");
    return true;
  } catch (err) {
    p.setChannelDeliveryError(
      err instanceof Error ? err.message : "Failed to save delivery target",
    );
    return false;
  } finally {
    p.setChannelDeliveryLoading(false);
  }
}

async function deleteDeliveryTarget(p: Props, target: AdminChannelDeliveryTargetRow) {
  try {
    await p.readJson(
      `/admin/chat/api/panel/channel-delivery-targets/${target.id}`,
      { method: "DELETE" },
    );
    p.setChannelDeliveryTargets((prev) =>
      prev.filter((row) => row.id !== target.id),
    );
  } catch (err) {
    alert(
      err instanceof Error ? err.message : "Failed to remove delivery target",
    );
  }
}

async function removeChannel(p: Props, channel: AdminChannelRow) {
  if (!confirm(`Remove channel "${channel.name}"?`)) {
    return;
  }
  try {
    await p.readJson(`/admin/chat/api/panel/channels/${channel.id}`, {
      method: "DELETE",
    });
    p.reloadChannelsTab();
  } catch (err) {
    alert(err instanceof Error ? err.message : "Delete failed");
  }
}

async function saveChannel(p: Props) {
  if (!p.configuringChannel) {
    return;
  }
  p.setChannelFormLoading(true);
  p.setChannelFormError(null);
  try {
    const configToSave = p.channelShowRawJson
      ? (JSON.parse(p.channelConfigJson) as Record<string, unknown>)
      : p.channelFormValues;
    const endpoint =
      p.configuringChannel.id == null
        ? "/admin/chat/api/panel/channels"
        : `/admin/chat/api/panel/channels/${p.configuringChannel.id}`;
    await p.readJson(endpoint, {
      method: p.configuringChannel.id == null ? "POST" : "PUT",
      body: JSON.stringify({
        plugin_id: p.configuringChannel.plugin_id,
        name: p.channelFormName,
        project_id: p.channelFormProjectId || null,
        enabled: p.channelFormEnabled,
        config: configToSave,
      }),
    });
    p.setConfiguringChannel(null);
    p.reloadChannelsTab();
  } catch (err) {
    p.setChannelFormError(
      err instanceof Error ? err.message : "Failed to save",
    );
  } finally {
    p.setChannelFormLoading(false);
  }
}

export function adminChannelActions(p: Props) {
  return {
    openAddChannel: () => openAddChannel(p),
    closeAddChannel: () => closeAddChannel(p),
    openChannelConfig: (channel: AdminChannelRow) => openChannelConfig(p, channel),
    closeChannelConfig: () => closeChannelConfig(p),
    selectChannelTemplate: (channel: AdminChannelRow) => selectChannelTemplate(p, channel),
    updateChannelEnabled: (channel: AdminChannelRow, enabled: boolean) => updateChannelEnabled(p, channel, enabled),
    reloadChannel: (channel: AdminChannelRow) => reloadChannel(p, channel),
    createDeliveryTarget: () => createDeliveryTarget(p),
    deleteDeliveryTarget: (target: AdminChannelDeliveryTargetRow) => deleteDeliveryTarget(p, target),
    removeChannel: (channel: AdminChannelRow) => removeChannel(p, channel),
    saveChannel: () => saveChannel(p),
  };
}
