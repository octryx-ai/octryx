// Types of a Workspace's own connection, the products that can have one and the record guard for server answers.
import type { AtlassianProduct } from "../connectorsTab/atlassianAuthModes";

export const CONNECTION_PRODUCTS: readonly AtlassianProduct[] = [
  "confluence",
  "jira",
];

export type ConnectionMode = "global" | "own";
export type ConnectionHealth = {
  status: "ok" | "failing" | "unknown";
  checkedAt: string | null;
};

export type WorkspaceConnection = {
  mode: ConnectionMode;
  /** Whether the global connection is set up (shown next to "Use global connection"). */
  globalConfigured: boolean;
  /** Whether the global entry is switched on. */
  globalActive: boolean;
  publicFields: Record<string, unknown>;
  secretStatus: Record<string, boolean>;
  health: ConnectionHealth | null;
  /**
   * The server's computed `state` is `own_incomplete` (an own unit lacking URL, mode or
   * credential) or `own_disabled` (an own entry whose connector is switched off for the Workspace). Either way the
   * own connection cannot serve runtime access.
   */
  incomplete: boolean;
  /** The server's fixed `state_summary` for an incomplete or disabled own connection, else null. */
  stateSummary: string | null;
};

export const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);
