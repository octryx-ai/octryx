import { useEffect, useState } from "react";

import { loadPolicyReferences } from "./policyEngineApi";

type Group = { count: number; policies: { id: string; name: string }[] };
export type PolicyReferences = { connectors: Record<string, Group>; connectorWide: Record<string, Group>; connections: Record<string, Group> };

const TTL_MS = 30_000;
let cache: { at: number; value: Promise<PolicyReferences | null> } | null = null;

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
function groups(raw: unknown): Record<string, Group> {
  if (!isRecord(raw)) return {};
  return Object.fromEntries(Object.entries(raw).filter(([, value]) => isRecord(value)).map(([key, value]) => {
    const group = value as Record<string, unknown>;
    const policies = Array.isArray(group.policies) ? group.policies.filter(isRecord).map((item) => ({ id: String(item.id ?? ""), name: String(item.name ?? item.id ?? "") })) : [];
    return [key, { count: typeof group.count === "number" ? group.count : policies.length, policies }];
  }));
}

export function readPolicyReferences(raw: unknown): PolicyReferences {
  const value = isRecord(raw) ? raw : {};
  return { connectors: groups(value.connectors), connectorWide: groups(value.connector_wide), connections: groups(value.connections) };
}

export function resetPolicyReferences(): void {
  cache = null;
}

// Which policies name a connector or a named connection: for the connector cards. Platform admins
// only — for anyone else the request is refused and nothing is shown. One request per 30 seconds for all cards.
export function usePolicyReferences(): PolicyReferences | null {
  const [references, setReferences] = useState<PolicyReferences | null>(null);
  useEffect(() => {
    let alive = true;
    if (!cache || Date.now() - cache.at > TTL_MS) {
      cache = { at: Date.now(), value: loadPolicyReferences().then(readPolicyReferences).catch(() => null) };
    }
    void cache.value.then((value) => { if (alive) setReferences(value); });
    return () => { alive = false; };
  }, []);
  return references;
}
