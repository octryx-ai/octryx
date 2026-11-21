import { readJson } from "../../utils/adminPanelHelpers";

// Plugins (plugins contract §6, backend routes/plugins.py): the image's plugins, switched on per Workspace; a
// Workspace's installs (pages, settings) and what the last start did with the image's folder. Field
// names follow the backend.

export type PluginScope = "workspace" | "platform";
export type PluginStatus = "active" | "disabled";

export type PluginFinding = {
  id: string;
  rule: string;
  severity: string;
  message: string;
  file?: string | null;
  line?: number | null;
  effect?: string;
  acknowledge?: boolean;
  blocks?: boolean;
  // Only in the install view and in blocking_findings: the skill the finding belongs to.
  skill?: string;
};

export type PluginConflict = {
  kind: "plugin" | "skill" | "workflow" | "role" | "function" | "mcp_server";
  key: string;
  code: string;
  message: string;
};

export type PluginSource =
  | { kind: "upload"; filename: string }
  | { kind: "git"; url: string; ref: string; path: string; commit: string }
  // From the image's plugin folder (contract §5); missing_from_image: switched off because the image no longer has it.
  | { kind: "image"; entry: string; folder: string; package_digest?: string; missing_from_image?: boolean };

export type PluginUiSlot = { id: string; title: string; where?: string | null; entry?: string };
export type PluginUi = { bundle?: string | null; methods?: string[]; pages?: PluginUiSlot[]; tiles?: PluginUiSlot[]; tabs?: PluginUiSlot[]; phone?: PluginUiSlot[] };

export type PluginPermissions = {
  connections: string[];
  egress: string[];
  writes: string[];
  skills: { name: string; description: string }[];
  workflows: { key: string; name: string; writes: string[] }[];
  roles: { key: string; name: string; function_keys: string[] }[];
  functions: { key: string; name: string; description?: string; tools: string[] }[];
  mcp_servers: { name: string; url: string; transport: string; tools: string[] }[];
  server: Record<string, unknown> | null;
  ui: PluginUi | null;
  settings?: Record<string, unknown> | null;
};

export type PluginContribution = {
  kind: "skill" | "workflow" | "role" | "function" | "mcp_server";
  id: string;
  key: string;
  created: boolean;
  // Contract §5: an upgrade no longer brings it; switched off and kept.
  dropped?: boolean;
};

export type PluginInstall = {
  id: string;
  plugin: string;
  name: string;
  version: string;
  publisher: string;
  description: string;
  scope: PluginScope;
  workspace_id: string | null;
  status: PluginStatus;
  source: PluginSource;
  package_digest: string;
  consent_digest: string;
  permissions: PluginPermissions;
  contributions: PluginContribution[];
  findings: PluginFinding[];
  ui: PluginUi | null;
  installed_by: string;
  // The names of who installed and last changed it (every viewer gets them; null when the user is gone).
  installed_by_name?: string | null;
  installed_at: string | null;
  updated_by: string;
  updated_by_name?: string | null;
  updated_at: string | null;
};

// What the viewer may do with the list they asked for (GET /api/v1/plugins).

// What the last start did with the image's plugin folder (GET /api/v1/plugins/image, platform admins).
// available: new, on in no Workspace yet.
export type ImageOutcome = "available" | "upgraded" | "unchanged" | "enabled" | "disabled" | "failed";
export type ImageEntry = {
  entry: string;
  outcome: ImageOutcome;
  plugin?: string;
  version?: string;
  from_version?: string;
  code?: string;
  message?: string;
  issues?: { code?: string; message: string; path?: string }[];
  conflicts?: PluginConflict[];
  blocking_findings?: PluginFinding[];
};
// folder_exists false: the image has no plugin folder, so nothing was changed.
export type ImageReport = { folder: string; folder_exists?: boolean; started_at: string | null; entries: ImageEntry[] };

// One plain line of what an image plugin brings (backend services/plugins/summary.py): `key` for translation
// (plugins.summary.brings|pages|uses|writes|connects), `text` in English, `params` its values.
export type SummaryLine = { key: string; text: string; params?: Record<string, unknown> };

// A plugin of the Octryx image and whether it is on in the Workspace asked for (GET /api/v1/plugins/available).
export type AvailablePlugin = {
  plugin: string;
  name: string;
  version: string;
  publisher: string;
  description: string;
  // false: missing from the image at the last start, switched off everywhere.
  in_image: boolean;
  summary: SummaryLine[];
  active: boolean;
  // The Workspace's install (UI, settings, bridge); null until first switched on.
  install_id: string | null;
  needs_settings: boolean;
  // Live: in how many Workspaces it is on now.
  active_workspaces?: number;
};
export type AvailableViewer = { is_platform_admin: boolean; can_activate: boolean };
export type AvailableList = { plugins: AvailablePlugin[]; viewer: AvailableViewer | null };

const BASE = "/api/v1/plugins";
const id = (value: string) => encodeURIComponent(value);
const post = <T>(path: string, body?: unknown) =>
  readJson<T>(`${BASE}${path}`, { method: "POST", ...(body === undefined ? {} : { body: JSON.stringify(body) }) });

/** The image's plugins; with a Workspace, whether each is on there (members read, its admins switch). */
export async function listAvailable(workspaceId: string | null): Promise<AvailableList> {
  const query = workspaceId ? `?workspace_id=${id(workspaceId)}` : "";
  const payload = await readJson<{ plugins?: AvailablePlugin[]; viewer?: AvailableViewer }>(`${BASE}/available${query}`);
  return { plugins: payload.plugins ?? [], viewer: payload.viewer ?? null };
}

/** Switch an image plugin on or off in a Workspace; answers the Workspace's install. */
export const switchPlugin = (plugin: string, workspaceId: string, on: boolean) =>
  post<PluginInstall>(`/available/${id(plugin)}/${on ? "activate" : "deactivate"}`, { workspace_id: workspaceId });

export const loadPlugin = (installId: string) => readJson<PluginInstall>(`${BASE}/${id(installId)}`);

export const loadImageReport = () => readJson<ImageReport>(`${BASE}/image`);

