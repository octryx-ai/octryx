import type { ApprovalSummary } from "../../../chatDecisionTypes";
import { readJson } from "../../utils/adminPanelHelpers";
import type { SettingsSchema } from "./pluginSettingsModel";
import type { PluginUiView } from "./pluginUiModel";

// Plugin UI requests: a frame's view, the bridge, the settings, and the approval a bridge
// call waits for. Desktop uses the admin `readJson`; the phone passes its own `api` (it renews the phone session), so
// every function takes the fetcher.

export type Fetcher = <T>(path: string, init?: RequestInit) => Promise<T>;

const BASE = "/api/v1/plugins";
const id = (value: string) => encodeURIComponent(value);

export const desktopFetch: Fetcher = (path, init) => readJson(path, init);

export const loadPluginUi = (fetcher: Fetcher, installId: string) => fetcher<PluginUiView>(`${BASE}/${id(installId)}/ui`);

export const callBridge = (fetcher: Fetcher, installId: string, body: { method: string; params: Record<string, unknown>; context: { workspace_id?: string } }) =>
  fetcher<unknown>(`${BASE}/${id(installId)}/bridge`, { method: "POST", body: JSON.stringify(body) });

export type PluginSettings = { schema: SettingsSchema; values: Record<string, unknown> };

export const loadPluginSettings = (installId: string) => readJson<PluginSettings>(`${BASE}/${id(installId)}/settings`);

export const savePluginSettings = (installId: string, values: Record<string, unknown>) =>
  readJson<PluginSettings>(`${BASE}/${id(installId)}/settings`, { method: "PUT", body: JSON.stringify({ values }) });

// ---- the approval of a bridge call (the chat's approval API) -----------------------------------------------------

/**
 * Approve or reject through the chat's own approval route (POST /chat/api/approvals/{id}/approve|reject): the one
 * route the web and the phone both decide a session approval with; it checks who may decide.
 */
export const decideApproval = (fetcher: Fetcher, approvalId: string, decision: "approve" | "reject") =>
  fetcher<unknown>(`/chat/api/approvals/${id(approvalId)}/${decision}`, { method: "POST" });

/**
 * The approval with its change preview, as the chat shows it: the approval's session (GET /api/v1/approvals/{id})
 * and that session's view (the plugin's own per-viewer session). Null when either is not readable; the dialog then
 * shows the tool in words only.
 */
export async function loadApprovalWithPreview(fetcher: Fetcher, approvalId: string): Promise<ApprovalSummary | null> {
  try {
    const meta = await fetcher<{ session_id?: string | null }>(`/api/v1/approvals/${id(approvalId)}`);
    if (!meta.session_id) return null;
    const view = await fetcher<{ selectedApprovals?: ApprovalSummary[] }>(`/chat/api/sessions/${id(meta.session_id)}/view`);
    return (view.selectedApprovals ?? []).find((item) => item.id === approvalId) ?? null;
  } catch {
    return null;
  }
}
