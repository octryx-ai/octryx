// Alerts about run and device problems: the backend announces a problem
// with a run or a device job as the notification "problem.raised" to the Workspace's admins and to the run's requester
// and responsible person (the job's owner). Email, Slack and Teams carry it through notification subscriptions: a
// person's own (user_id set) and a Workspace's (user_id empty, project_id set). A subscription to problem.raised is its
// own switch; the person's global channel preferences gate only "*" subscriptions, so this page never touches them.
// Pure functions only, so the page logic is testable without a browser.

export const PROBLEM_EVENT = "problem.raised";
export const PROBLEM_EVENT_LABEL = "Run and device problems";
// A test send answers with the delivery-log row while it is still pending, so the message says no more.
export const TEST_SENT = "Test sent; it is being delivered.";

export type AlertChannel = "email" | "slack" | "teams";

export type AlertChannelInfo = {
  key: AlertChannel;
  label: string;
  // The channel configuration's plugin id (Connections › Channels).
  plugin: string;
  targetLabel: string;
  placeholder: string;
};

export const ALERT_CHANNELS: AlertChannelInfo[] = [
  { key: "email", label: "Email", plugin: "email", targetLabel: "Email address", placeholder: "name@example.com" },
  { key: "slack", label: "Slack", plugin: "slack", targetLabel: "Slack channel or member ID", placeholder: "C0123ABCD" },
  { key: "teams", label: "Microsoft Teams", plugin: "msteams", targetLabel: "Teams target", placeholder: "serviceUrl|conversationId" },
];

export function channelInfo(channel: string): AlertChannelInfo | null {
  return ALERT_CHANNELS.find((item) => item.key === channel) ?? null;
}

export function channelLabel(channel: string): string {
  return channelInfo(channel)?.label ?? channel;
}

// The API's NotificationSubscriptionResponse.
export type NotificationSubscription = {
  id: string;
  user_id: string | null;
  project_id: string | null;
  event_type: string;
  channel_type: string;
  channel_config_id: number | null;
  target: string;
  template_id: string | null;
  is_active: boolean;
  created_at: string | null;
};

// The API's NotificationSubscriptionRequest.
export type SubscriptionRequest = {
  user_id: string | null;
  project_id: string | null;
  event_type: string;
  channel_type: string;
  channel_config_id: number | null;
  target: string;
  template_id: string | null;
  is_active: boolean;
};

const text = (value: unknown): string | null => (typeof value === "string" && value.trim() ? value : null);

function readSubscription(value: unknown): NotificationSubscription | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const id = text(row.id);
  const channel = text(row.channel_type);
  if (!id || !channel) return null;
  return {
    id,
    user_id: text(row.user_id),
    project_id: text(row.project_id),
    event_type: text(row.event_type) ?? "*",
    channel_type: channel,
    channel_config_id: typeof row.channel_config_id === "number" ? row.channel_config_id : null,
    target: typeof row.target === "string" ? row.target : "",
    template_id: text(row.template_id),
    is_active: row.is_active !== false,
    created_at: text(row.created_at),
  };
}

export function readSubscriptions(payload: unknown): NotificationSubscription[] {
  if (!Array.isArray(payload)) return [];
  return payload.map(readSubscription).filter((row): row is NotificationSubscription => row !== null);
}

/** The person's own problem subscription on a channel: the active one first, else the newest. */
export function personalProblemSubscription(
  subscriptions: NotificationSubscription[],
  channel: AlertChannel,
): NotificationSubscription | null {
  const mine = subscriptions.filter(
    (row) => row.user_id && row.event_type === PROBLEM_EVENT && row.channel_type === channel,
  );
  return mine.find((row) => row.is_active) ?? mine[0] ?? null;
}

/** A personal channel is on while its problem subscription is active. */
export function personalChannelOn(subscription: NotificationSubscription | null): boolean {
  return Boolean(subscription?.is_active);
}

/** The request body for a subscription to run and device problems; `base` keeps the fields the form does not show. */
export function problemSubscriptionRequest(
  draft: { channel: AlertChannel; target: string; projectId: string | null; channelConfigId: number | null; active: boolean },
  base?: NotificationSubscription | null,
): SubscriptionRequest {
  return {
    user_id: base?.user_id ?? null,
    project_id: draft.projectId,
    event_type: PROBLEM_EVENT,
    channel_type: draft.channel,
    channel_config_id: draft.channelConfigId,
    target: draft.target.trim(),
    template_id: base?.template_id ?? null,
    is_active: draft.active,
  };
}

/** The same subscription switched on or off, everything else unchanged. */
export function withActive(subscription: NotificationSubscription, active: boolean): SubscriptionRequest {
  return {
    user_id: subscription.user_id,
    project_id: subscription.project_id,
    event_type: subscription.event_type,
    channel_type: subscription.channel_type,
    channel_config_id: subscription.channel_config_id,
    target: subscription.target,
    template_id: subscription.template_id,
    is_active: active,
  };
}

/** A Workspace's problem alerts: no person, a Workspace, event problem.raised; grouped by Workspace, then channel. */
export function workspaceProblemSubscriptions(
  subscriptions: NotificationSubscription[],
  workspaceName: (id: string) => string,
): NotificationSubscription[] {
  const order = (channel: string) => {
    const index = ALERT_CHANNELS.findIndex((item) => item.key === channel);
    return index < 0 ? ALERT_CHANNELS.length : index;
  };
  return subscriptions
    .filter((row) => !row.user_id && row.project_id && row.event_type === PROBLEM_EVENT)
    .sort((a, b) =>
      workspaceName(a.project_id ?? "").localeCompare(workspaceName(b.project_id ?? ""))
      || order(a.channel_type) - order(b.channel_type)
      || a.target.localeCompare(b.target));
}

export type ChannelConnection = { id: number | null; plugin_id: string; enabled: boolean };

/** A Workspace alert's state: off, waiting for a channel connection that can send it, or active. */
export function workspaceAlertState(
  subscription: NotificationSubscription,
  connections: ChannelConnection[],
): "Active" | "Off" | "Needs configuration" {
  if (!subscription.is_active) return "Off";
  const plugin = channelInfo(subscription.channel_type)?.plugin;
  const usable = connections.some((item) => item.id != null && item.enabled && item.plugin_id === plugin
    && (subscription.channel_config_id == null || item.id === subscription.channel_config_id));
  return usable ? "Active" : "Needs configuration";
}
