import { useState } from "react";
import type {
  AdminChannelDeliveryLogRow as AdminChannelDeliveryLog,
  AdminChannelDeliveryTargetRow as AdminChannelDeliveryTarget,
  AdminChannelRow as AdminChannel,
  AdminChannelSessionRow as AdminChannelSession,
} from "../components/channelTypes";

export function useAdminChannelState() {
  const [channels, setChannels] = useState<AdminChannel[]>([]);
  const [channelSessions, setChannelSessions] = useState<AdminChannelSession[]>(
    [],
  );
  const [channelDeliveryTargets, setChannelDeliveryTargets] = useState<
    AdminChannelDeliveryTarget[]
  >([]);
  const [channelDeliveryLogs, setChannelDeliveryLogs] = useState<
    AdminChannelDeliveryLog[]
  >([]);
  const [channelDeliveryProjectId, setChannelDeliveryProjectId] = useState("");
  const [channelDeliveryEventType, setChannelDeliveryEventType] =
    useState("approval.requested");
  const [channelDeliveryChannelId, setChannelDeliveryChannelId] = useState("");
  const [channelDeliveryTarget, setChannelDeliveryTarget] = useState("");
  const [channelDeliveryLoading, setChannelDeliveryLoading] = useState(false);
  const [channelDeliveryError, setChannelDeliveryError] = useState<
    string | null
  >(null);
  const [configuringChannel, setConfiguringChannel] =
    useState<AdminChannel | null>(null);
  const [channelConfigJson, setChannelConfigJson] = useState("");
  const [channelFormValues, setChannelFormValues] = useState<
    Record<string, unknown>
  >({});
  const [channelFormName, setChannelFormName] = useState("");
  const [channelFormProjectId, setChannelFormProjectId] = useState("");
  const [channelShowRawJson, setChannelShowRawJson] = useState(false);
  const [channelFormEnabled, setChannelFormEnabled] = useState(false);
  const [channelFormLoading, setChannelFormLoading] = useState(false);
  const [channelFormError, setChannelFormError] = useState<string | null>(null);
  const [showAddChannel, setShowAddChannel] = useState(false);
  const [channelCatalogSearch, setChannelCatalogSearch] = useState("");
  const [availableChannels, setAvailableChannels] = useState<AdminChannel[]>(
    [],
  );
  const [availableLoading, setAvailableLoading] = useState(false);

  return {
    availableChannels,
    setAvailableChannels,
    availableLoading,
    setAvailableLoading,
    channelCatalogSearch,
    setChannelCatalogSearch,
    channelConfigJson,
    setChannelConfigJson,
    channelFormEnabled,
    setChannelFormEnabled,
    channelFormError,
    setChannelFormError,
    channelFormLoading,
    setChannelFormLoading,
    channelFormName,
    setChannelFormName,
    channelFormProjectId,
    setChannelFormProjectId,
    channelFormValues,
    setChannelFormValues,
    channels,
    setChannels,
    channelSessions,
    setChannelSessions,
    channelDeliveryTargets,
    setChannelDeliveryTargets,
    channelDeliveryLogs,
    setChannelDeliveryLogs,
    channelDeliveryProjectId,
    setChannelDeliveryProjectId,
    channelDeliveryEventType,
    setChannelDeliveryEventType,
    channelDeliveryChannelId,
    setChannelDeliveryChannelId,
    channelDeliveryTarget,
    setChannelDeliveryTarget,
    channelDeliveryLoading,
    setChannelDeliveryLoading,
    channelDeliveryError,
    setChannelDeliveryError,
    channelShowRawJson,
    setChannelShowRawJson,
    configuringChannel,
    setConfiguringChannel,
    showAddChannel,
    setShowAddChannel,
  };
}
