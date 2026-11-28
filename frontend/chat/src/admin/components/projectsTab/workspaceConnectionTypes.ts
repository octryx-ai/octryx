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
  globalConfigured: boolean;
  globalActive: boolean;
  publicFields: Record<string, unknown>;
  secretStatus: Record<string, boolean>;
  health: ConnectionHealth | null;
  incomplete: boolean;
  stateSummary: string | null;
};

export const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);
