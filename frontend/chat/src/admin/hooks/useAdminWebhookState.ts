import { useMemo, useState } from "react";
import type {
  AdminOutboundWebhookDeliveryRow as AdminOutboundWebhookDelivery,
  AdminOutboundWebhookRow as AdminOutboundWebhook,
  AdminConnectorWatcherEventRow as AdminConnectorWatcherEvent,
  AdminConnectorWatcherRuleDecisionRow as AdminConnectorWatcherRuleDecision,
  AdminConnectorWatcherRuleRow as AdminConnectorWatcherRule,
  AdminConnectorWatcherRow as AdminConnectorWatcher,
  AdminWebhookRow as AdminWebhook,
} from "../components/webhookTypes";
import { orderKeys } from "./orderKeys";

function useInboundWebhookState() {
  const [webhooks, setWebhooks] = useState<AdminWebhook[]>([]);
  const [showCreateWebhook, setShowCreateWebhook] = useState(false);
  const [editingWebhookId, setEditingWebhookId] = useState<string | null>(null);
  const [webhookFormName, setWebhookFormName] = useState("");
  const [webhookFormDescription, setWebhookFormDescription] = useState("");
  const [webhookFormProjectId, setWebhookFormProjectId] = useState("");
  const [webhookFormSourceType, setWebhookFormSourceType] = useState("generic");
  // No hidden default: the webhook form needs an explicit permission-mode choice.
  const [webhookFormAgentType, setWebhookFormAgentType] = useState("");
  const [webhookFormActive, setWebhookFormActive] = useState(true);
  const [webhookFormLoading, setWebhookFormLoading] = useState(false);
  const [webhookFormError, setWebhookFormError] = useState<string | null>(null);
  return {
    webhooks, setWebhooks, showCreateWebhook, setShowCreateWebhook, editingWebhookId, setEditingWebhookId, webhookFormName,
    setWebhookFormName, webhookFormDescription, setWebhookFormDescription, webhookFormProjectId, setWebhookFormProjectId,
    webhookFormSourceType, setWebhookFormSourceType, webhookFormAgentType, setWebhookFormAgentType, webhookFormActive,
    setWebhookFormActive, webhookFormLoading, setWebhookFormLoading, webhookFormError, setWebhookFormError,
  };
}

function useOutboundWebhookState() {
  const [outboundWebhooks, setOutboundWebhooks] = useState<
    AdminOutboundWebhook[]
  >([]);
  const [outboundWebhookDeliveries, setOutboundWebhookDeliveries] = useState<
    AdminOutboundWebhookDelivery[]
  >([]);
  const [showOutboundDeliveries, setShowOutboundDeliveries] = useState(false);
  const [outboundWebhookDeliverySearch, setOutboundWebhookDeliverySearch] =
    useState("");
  const [showCreateOutboundWebhook, setShowCreateOutboundWebhook] =
    useState(false);
  const [editingOutboundWebhookId, setEditingOutboundWebhookId] = useState<
    string | null
  >(null);
  const [outboundWebhookFormName, setOutboundWebhookFormName] = useState("");
  const [outboundWebhookFormUrl, setOutboundWebhookFormUrl] = useState("");
  const [outboundWebhookFormProjectId, setOutboundWebhookFormProjectId] =
    useState("");
  const [outboundWebhookFormEvents, setOutboundWebhookFormEvents] = useState<
    string[]
  >(["task.completed"]);
  const [outboundWebhookFormLoading, setOutboundWebhookFormLoading] =
    useState(false);
  const [outboundWebhookFormError, setOutboundWebhookFormError] = useState<
    string | null
  >(null);
  const [createdOutboundSigningSecret, setCreatedOutboundSigningSecret] =
    useState<string | null>(null);
  return {
    outboundWebhooks, setOutboundWebhooks, outboundWebhookDeliveries, setOutboundWebhookDeliveries, showOutboundDeliveries,
    setShowOutboundDeliveries, outboundWebhookDeliverySearch, setOutboundWebhookDeliverySearch, showCreateOutboundWebhook,
    setShowCreateOutboundWebhook, editingOutboundWebhookId, setEditingOutboundWebhookId, outboundWebhookFormName,
    setOutboundWebhookFormName, outboundWebhookFormUrl, setOutboundWebhookFormUrl, outboundWebhookFormProjectId,
    setOutboundWebhookFormProjectId, outboundWebhookFormEvents, setOutboundWebhookFormEvents, outboundWebhookFormLoading,
    setOutboundWebhookFormLoading, outboundWebhookFormError, setOutboundWebhookFormError, createdOutboundSigningSecret,
    setCreatedOutboundSigningSecret,
  };
}

function useConnectorWatcherState() {
  const [connectorWatchers, setConnectorWatchers] = useState<
    AdminConnectorWatcher[]
  >([]);
  const [connectorWatcherEvents, setConnectorWatcherEvents] = useState<
    AdminConnectorWatcherEvent[]
  >([]);
  const [connectorWatcherRules, setConnectorWatcherRules] = useState<
    AdminConnectorWatcherRule[]
  >([]);
  const [connectorWatcherRuleDecisions, setConnectorWatcherRuleDecisions] =
    useState<AdminConnectorWatcherRuleDecision[]>([]);
  return {
    connectorWatchers, setConnectorWatchers, connectorWatcherEvents, setConnectorWatcherEvents, connectorWatcherRules,
    setConnectorWatcherRules, connectorWatcherRuleDecisions, setConnectorWatcherRuleDecisions,
  };
}

function filterDeliveries(deliveries: AdminOutboundWebhookDelivery[], query: string) {
  const search = query.trim().toLowerCase();
  if (!search) {
    return deliveries;
  }
  return deliveries.filter((delivery) =>
    [
      delivery.event_type,
      delivery.status,
      delivery.request_id,
      delivery.webhook_id,
      delivery.error,
      delivery.response_body,
      delivery.http_status?.toString() ?? "",
    ]
      .join(" ")
      .toLowerCase()
      .includes(search),
  );
}

// The order of the returned keys, as callers have always seen it.
const WEBHOOK_STATE_KEYS = [
  "createdOutboundSigningSecret", "setCreatedOutboundSigningSecret", "connectorWatcherEvents", "setConnectorWatcherEvents",
  "connectorWatcherRuleDecisions", "setConnectorWatcherRuleDecisions", "connectorWatcherRules", "setConnectorWatcherRules",
  "connectorWatchers", "setConnectorWatchers", "editingWebhookId", "setEditingWebhookId", "filteredOutboundWebhookDeliveries",
  "outboundWebhookDeliveries", "setOutboundWebhookDeliveries", "outboundWebhookDeliverySearch", "setOutboundWebhookDeliverySearch",
  "outboundWebhookFormError", "setOutboundWebhookFormError", "outboundWebhookFormEvents", "setOutboundWebhookFormEvents",
  "outboundWebhookFormLoading", "setOutboundWebhookFormLoading", "outboundWebhookFormName", "setOutboundWebhookFormName",
  "outboundWebhookFormProjectId", "setOutboundWebhookFormProjectId", "outboundWebhookFormUrl", "setOutboundWebhookFormUrl",
  "outboundWebhooks", "setOutboundWebhooks", "showCreateOutboundWebhook", "setShowCreateOutboundWebhook",
  "editingOutboundWebhookId", "setEditingOutboundWebhookId", "showCreateWebhook", "setShowCreateWebhook",
  "showOutboundDeliveries", "setShowOutboundDeliveries", "webhookFormActive", "setWebhookFormActive", "webhookFormAgentType",
  "setWebhookFormAgentType", "webhookFormDescription", "setWebhookFormDescription", "webhookFormError", "setWebhookFormError",
  "webhookFormLoading", "setWebhookFormLoading", "webhookFormName", "setWebhookFormName", "webhookFormProjectId",
  "setWebhookFormProjectId", "webhookFormSourceType", "setWebhookFormSourceType", "webhooks", "setWebhooks",
] as const;

export function useAdminWebhookState() {
  const inbound = useInboundWebhookState();
  const outbound = useOutboundWebhookState();
  const watchers = useConnectorWatcherState();
  const { outboundWebhookDeliveries, outboundWebhookDeliverySearch } = outbound;

  const filteredOutboundWebhookDeliveries = useMemo(
    () => filterDeliveries(outboundWebhookDeliveries, outboundWebhookDeliverySearch),
    [outboundWebhookDeliveries, outboundWebhookDeliverySearch],
  );

  return orderKeys({ ...inbound, ...outbound, ...watchers, filteredOutboundWebhookDeliveries }, WEBHOOK_STATE_KEYS);
}
