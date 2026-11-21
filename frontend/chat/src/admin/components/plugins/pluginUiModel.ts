import type { PluginInstall, PluginUiSlot } from "./pluginsApi";
import { isRecord } from "./pluginRecordGuard";

// The pure part of a plugin's UI in Octryx. What a frame message is, which
// calls may reach the bridge, where a plugin's pages, tiles and tabs go, the settings form from the plugin's schema,
// and every refusal in words. No DOM and no requests, so the unit tests cover it.

// ---- the frame's view of an install (GET /api/v1/plugins/{id}/ui) ------------------------------------------------

export type PluginSlots = { pages: PluginUiSlot[]; tiles: PluginUiSlot[]; tabs: PluginUiSlot[]; phone: PluginUiSlot[] };

export type PluginUiView = {
  install_id: string;
  plugin: string;
  version: string;
  // "/plugin-ui/{install}/{token}/": the token in the path is the frame's only credential (one hour).
  base_url: string;
  expires_in: number;
  slots: PluginSlots;
  methods: string[];
};

export const FRAME_MIN_HEIGHT = 120;
export const FRAME_MAX_HEIGHT = 4000;
// The /ui token lives one hour; the frame fetches a new one and reloads after 50 minutes.
export const FRAME_REFRESH_MS = 50 * 60 * 1000;

/** The iframe's address: the view's base URL plus the slot's entry file (never an absolute or parent path). */
export function frameSrc(view: Pick<PluginUiView, "base_url">, slot: Pick<PluginUiSlot, "entry"> | null): string {
  const entry = String(slot?.entry || "index.html").replace(/^\/+/, "");
  const safe = entry.split("/").some((part) => part === ".." || part === "") ? "index.html" : entry;
  return `${view.base_url.endsWith("/") ? view.base_url : `${view.base_url}/`}${safe}`;
}

export function clampHeight(height: unknown): number | null {
  const value = typeof height === "number" ? height : Number.NaN;
  if (!Number.isFinite(value)) return null;
  return Math.min(FRAME_MAX_HEIGHT, Math.max(FRAME_MIN_HEIGHT, Math.ceil(value)));
}

// ---- postMessage envelope (plugin → frame) -----------------------------------------------------------------------

export type FrameMessage =
  | { kind: "ready" }
  | { kind: "resize"; height: number }
  | { kind: "call"; id: string; method: string; params: Record<string, unknown> };

/**
 * A message from the plugin's frame, or null for anything else. The caller has already checked that it came from
 * this iframe's window (`event.source`); here only the shape counts: `v: 1`, a known type, or a call with a string id
 * and method (ids up to 64 characters, methods up to 200 as the bridge accepts).
 */
export function readFrameMessage(data: unknown): FrameMessage | null {
  if (!isRecord(data) || data.v !== 1) return null;
  if (data.type === "ready") return { kind: "ready" };
  if (data.type === "resize") {
    const height = clampHeight(data.height);
    return height === null ? null : { kind: "resize", height };
  }
  if (data.type !== undefined) return null;
  const { id, method } = data;
  if (typeof id !== "string" || !id || id.length > 64) return null;
  if (typeof method !== "string" || !method || method.length > 200) return null;
  const params = isRecord(data.params) ? data.params : {};
  return { kind: "call", id, method, params };
}

export type BridgeError = { code: string; message: string; approval?: PluginApproval };
export type BridgeOutcome = { result: unknown } | { error: BridgeError };
export type PluginApproval = { approval_id?: string; change_preview_id?: string; tool_name?: string };

/** Only methods the install's /ui declares reach the bridge; anything else is answered here and never sent. */
export function methodAllowed(view: Pick<PluginUiView, "methods"> | null, method: string): boolean {
  return Boolean(view && view.methods.includes(method));
}

export function undeclaredError(method: string): BridgeError {
  return { code: "plugin_method_not_declared", message: `'${method}' is not a method this plugin declares.` };
}

/** The bridge's `context`: a platform install runs in the viewer's current Workspace, a Workspace install in its own. */
export function bridgeContext(scope: PluginInstall["scope"], workspaceId: string | null): { workspace_id?: string } {
  return scope === "platform" && workspaceId ? { workspace_id: workspaceId } : {};
}

/** A bridge answer (HTTP 200 `{result}` or `{error}`) in the envelope's shape; anything else is a failure. */
export function readBridgeOutcome(payload: unknown): BridgeOutcome {
  if (isRecord(payload) && isRecord(payload.error)) {
    const error = payload.error;
    const approval = isRecord(error.approval) ? (error.approval as PluginApproval) : undefined;
    return { error: { code: String(error.code || "tool_failed"), message: String(error.message || ""), ...(approval ? { approval } : {}) } };
  }
  if (isRecord(payload) && "result" in payload) return { result: payload.result };
  return { error: { code: "bridge_failed", message: "Octryx gave no answer." } };
}

/** A refused bridge request (HTTP 403/404/409/422) as the envelope's error, with its code and the server's message. */
export function bridgeRequestError(error: unknown): BridgeError {
  const value = isRecord(error) ? error : {};
  const code = typeof value.code === "string" && value.code ? value.code : "bridge_failed";
  const message = error instanceof Error && error.message && error.message !== code ? error.message : FRAME_ERROR_WORDS[code] ?? "The call failed.";
  return { code, message };
}

/** Whether a bridge error asks the person to confirm in Octryx (contract §4: a write that needs confirmation). */
export function confirmationOf(outcome: BridgeOutcome): PluginApproval | null {
  if (!("error" in outcome) || outcome.error.code !== "confirmation_required") return null;
  return outcome.error.approval ?? {};
}

/** "create_confluence_page" → "Create Confluence page"; "<server>.<tool>" → the tool's words. */
export function toolWords(toolName: string | null | undefined): string {
  const raw = String(toolName || "").replace(/^mcp__.+?__/, "").split(".").pop() || "";
  const spaced = raw.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim().toLowerCase();
  if (!spaced) return "Change something";
  const named = spaced.replace(/\b(jira|confluence|github|gitlab|bitbucket|slack)\b/g, (word) =>
    ({ github: "GitHub", gitlab: "GitLab" } as Record<string, string>)[word] ?? word.charAt(0).toUpperCase() + word.slice(1));
  return named.charAt(0).toUpperCase() + named.slice(1);
}

// ---- why a frame shows nothing ----------------------------------------------------------------------------------

const FRAME_ERROR_WORDS: Record<string, string> = {
  plugin_disabled: "The plugin is disabled.",
  plugin_has_no_ui: "This plugin brings no pages.",
  plugin_not_found: "The plugin is not installed here.",
  plugin_ui_token_expired: "The plugin's access expired. Reload the page.",
  workspace_not_found: "Choose a Workspace you are a member of.",
  plugin_workspace_required: "Choose a Workspace first.",
  plugin_method_not_declared: "The plugin asked for something it did not declare.",
};

/** The one muted line of a frame that could not load, with the server's message as its title. */
export function frameLoadError(error: unknown): { text: string; title: string } {
  const value = isRecord(error) ? error : {};
  const code = typeof value.code === "string" ? value.code : "";
  const message = error instanceof Error && error.message && error.message !== code ? error.message : "";
  return { text: "Plugin could not load", title: message || FRAME_ERROR_WORDS[code] || "" };
}

// ---- slots: where a plugin's pages go ---------------------------------------------------------------------------

export type PluginArea = "work" | "knowledge" | "operations" | "admin";
export type PluginSlotKind = "pages" | "tiles" | "tabs" | "phone";

export type PluginSlotEntry = {
  installId: string;
  plugin: string;
  pluginName: string;
  scope: PluginInstall["scope"];
  kind: PluginSlotKind;
  slot: PluginUiSlot;
  // "install:slot", the address of the entry (`plugin_page=` on desktop).
  key: string;
};

export function slotKey(installId: string, slotId: string): string {
  return `${installId}:${slotId}`;
}

export function parseSlotKey(value: string | null | undefined): { installId: string; slotId: string } | null {
  const match = /^([A-Za-z0-9-]{1,64}):([a-z0-9][a-z0-9-]{0,39})$/.exec(String(value || "").trim());
  return match ? { installId: match[1], slotId: match[2] } : null;
}

/**
 * Every slot of the active installs the viewer sees, from the list (each install's `ui`): pages per area, tiles per
 * host, tabs per host, phone pages. A disabled install or one without a bundle brings none.
 */
export function collectSlots(installs: Pick<PluginInstall, "id" | "plugin" | "name" | "scope" | "status" | "ui">[]): PluginSlotEntry[] {
  const out: PluginSlotEntry[] = [];
  for (const install of installs) {
    if (install.status !== "active" || !install.ui || !install.ui.bundle) continue;
    for (const kind of ["pages", "tiles", "tabs", "phone"] as PluginSlotKind[]) {
      for (const slot of install.ui[kind] ?? []) {
        if (!slot || !slot.id) continue;
        out.push({ installId: install.id, plugin: install.plugin, pluginName: install.name, scope: install.scope, kind, slot,
          key: slotKey(install.id, slot.id) });
      }
    }
  }
  return out;
}

/** The pages of one area, grouped under their plugin's name in name order (one group per plugin). */
export function pagesOfArea(entries: PluginSlotEntry[], area: PluginArea): { pluginName: string; installId: string; pages: PluginSlotEntry[] }[] {
  const groups = new Map<string, { pluginName: string; installId: string; pages: PluginSlotEntry[] }>();
  for (const entry of entries) {
    if (entry.kind !== "pages" || entry.slot.where !== area) continue;
    const group = groups.get(entry.installId) ?? { pluginName: entry.pluginName, installId: entry.installId, pages: [] };
    group.pages.push(entry);
    groups.set(entry.installId, group);
  }
  return [...groups.values()].sort((a, b) => a.pluginName.localeCompare(b.pluginName));
}

export function slotsOf(entries: PluginSlotEntry[], kind: PluginSlotKind, where?: string): PluginSlotEntry[] {
  return entries.filter((entry) => entry.kind === kind && (where === undefined || entry.slot.where === where));
}

// ---- theme ------------------------------------------------------------------------------------------------------

// The tokens a plugin gets (contract §4 context.theme.tokens; it maps them to CSS variables `--<name>`): the first
// CSS variable of the host that has a value. `bg` is the background behind the frame, measured by the caller.
export const THEME_TOKENS: Record<string, string[]> = {
  fg: ["--text"],
  muted: ["--muted"],
  line: ["--border-strong", "--border"],
  accent: ["--accent"],
  "on-accent": ["--ds-on-accent", "--on-accent"],
  panel: ["--panel-strong"],
  ok: ["--status-active"],
  bad: ["--status-error"],
  attention: ["--status-attention"],
  info: ["--status-running"],
  font: ["--font-sans"],
  mono: ["--font-mono"],
};

export function themeTokens(read: (name: string) => string, background: string): Record<string, string> {
  const tokens: Record<string, string> = {};
  if (background) tokens.bg = background;
  for (const [name, candidates] of Object.entries(THEME_TOKENS)) {
    const value = candidates.map((candidate) => read(candidate).trim()).find(Boolean);
    if (value) tokens[name] = value;
  }
  return tokens;
}
