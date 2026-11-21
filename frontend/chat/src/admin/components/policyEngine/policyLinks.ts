// Links into the Policies page from elsewhere: the connector cards, the named
// connections and Agents → Governance → Policy open the list filtered by a Workspace, a connector or a connection.
// The filter travels as URL parameters (the admin navigation keeps them); the Policies page reads them once and
// removes them, so a later visit starts unfiltered.

import type { AdminTab } from "../../types/adminPanelTypes.governance";

export type PolicyFilter = { workspace?: string; connection?: string; connector?: string };
export const POLICY_FILTER_PARAMS: Record<keyof PolicyFilter, string> = {
  workspace: "policyWorkspace", connection: "policyConnection", connector: "policyConnector",
};

type UrlEnv = { location: { href: string }; history: { replaceState: (data: unknown, unused: string, url: string) => void } };
const browser = (): UrlEnv | null => (typeof window !== "undefined" ? window : null);

export function writePolicyFilter(filter: PolicyFilter, env: UrlEnv | null = browser()): void {
  if (!env) return;
  const url = new URL(env.location.href);
  for (const [key, param] of Object.entries(POLICY_FILTER_PARAMS)) {
    const value = filter[key as keyof PolicyFilter];
    if (value) url.searchParams.set(param, value);
    else url.searchParams.delete(param);
  }
  env.history.replaceState(null, "", url.toString());
}

export function clearPolicyFilter(env: UrlEnv | null = browser()): void {
  if (!env) return;
  const url = new URL(env.location.href);
  if (!Object.values(POLICY_FILTER_PARAMS).some((param) => url.searchParams.has(param))) return;
  for (const param of Object.values(POLICY_FILTER_PARAMS)) url.searchParams.delete(param);
  env.history.replaceState(null, "", url.toString());
}

/** Open Settings → Governance → Policies filtered by `filter`. */
export function openPolicies(openTab: (tab: AdminTab) => void, filter: PolicyFilter, env: UrlEnv | null = browser()): void {
  writePolicyFilter(filter, env);
  openTab("cedarPolicies");
}
