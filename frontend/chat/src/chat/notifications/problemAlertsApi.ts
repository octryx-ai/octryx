import { readJson } from "../../admin/utils/adminPanelHelpers";
import { readSubscriptions, type NotificationSubscription, type SubscriptionRequest } from "./problemAlertsModel";

const PERSONAL = "/api/v1/notifications/subscriptions";
// Mounted on the admin surface without the /api/v1 prefix.
const WORKSPACE = "/admin/notification-subscriptions";

export type SubscriptionScope = "personal" | "workspace";

const base = (scope: SubscriptionScope) => (scope === "personal" ? PERSONAL : WORKSPACE);

export async function loadSubscriptions(scope: SubscriptionScope): Promise<NotificationSubscription[]> {
  return readSubscriptions(await readJson<unknown>(base(scope)));
}

export async function saveSubscription(
  scope: SubscriptionScope,
  body: SubscriptionRequest,
  id?: string,
): Promise<void> {
  await readJson<unknown>(id ? `${base(scope)}/${encodeURIComponent(id)}` : base(scope), {
    method: id ? "PUT" : "POST",
    body: JSON.stringify(body),
  });
}

export async function removeSubscription(scope: SubscriptionScope, id: string): Promise<void> {
  await readJson<unknown>(`${base(scope)}/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function sendTest(scope: SubscriptionScope, id: string): Promise<void> {
  await readJson<unknown>(`${base(scope)}/${encodeURIComponent(id)}/test`, { method: "POST" });
}
