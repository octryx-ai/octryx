import { readJson } from "../../admin/utils/adminPanelHelpers";
import { readSubscriptions, type NotificationSubscription, type SubscriptionRequest } from "./problemAlertsModel";

// The requests behind the alert settings. Refusals keep the server's message on the error (readJson), so the pages
// show it verbatim.

const PERSONAL = "/api/v1/notifications/subscriptions";
// Mounted on the admin surface without the /api/v1 prefix (http_setup ADMIN_SURFACE routers).
const WORKSPACE = "/admin/notification-subscriptions";

export type SubscriptionScope = "personal" | "workspace";

const base = (scope: SubscriptionScope) => (scope === "personal" ? PERSONAL : WORKSPACE);

export async function loadSubscriptions(scope: SubscriptionScope): Promise<NotificationSubscription[]> {
  return readSubscriptions(await readJson<unknown>(base(scope)));
}

/** Creates (no id) or replaces (id) a subscription. */
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

/** Queues a test message on the subscription; the answer is its delivery-log row, still pending. */
export async function sendTest(scope: SubscriptionScope, id: string): Promise<void> {
  await readJson<unknown>(`${base(scope)}/${encodeURIComponent(id)}/test`, { method: "POST" });
}
