// The global evidence-grounding setting, `agent.evidence_grounding_config`.
// Server contract (backend/app/services/system_config/evidence_domains.py and
// backend/app/web/routers/panel_evidence_grounding.py): the live key is `high_risk_agent_types`
// (a non-empty list; `null` resets to the seed list); an invalid list is refused with
// `invalid_high_risk_agent_types`.

export const EVIDENCE_GROUNDING_PATH = "/admin/chat/api/panel/evidence-grounding";

export type EvidenceGroundingSettings = {
  highRiskAgentTypes: string[];
  source: "default" | "configured";
  defaultAgentTypes: string[];
};

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

export function parseEvidenceGroundingSettings(payload: unknown): EvidenceGroundingSettings {
  const root = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {};
  return {
    highRiskAgentTypes: stringList(root.high_risk_agent_types),
    source: root.high_risk_agent_types_source === "configured" ? "configured" : "default",
    defaultAgentTypes: stringList(root.default_high_risk_agent_types),
  };
}

// One agent type per line or comma; blanks dropped, order kept, duplicates removed.
export function agentTypesFromDraft(draft: string): string[] {
  const seen = new Set<string>();
  const names: string[] = [];
  for (const raw of draft.split(/[\n,]/)) {
    const name = raw.trim().toLowerCase();
    if (name && !seen.has(name)) {
      seen.add(name);
      names.push(name);
    }
  }
  return names;
}

export function evidenceGroundingPatch(agentTypes: string[] | null) {
  return { high_risk_agent_types: agentTypes };
}
