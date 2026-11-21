// The Workspace setting `evidence_grounding_policy` as explicit states.
// Server contract (backend/app/services/evidence_grounding_settings.py): the stored section is
// `{"mode": "required" | "workflow"}` or `{}` (the default); any other value is refused with
// `unsupported_evidence_grounding_mode`, and `{"mode": null}` in a merge patch resets it.

export const EVIDENCE_GROUNDING_POLICY_KEY = "evidence_grounding_policy";

export type EvidenceGroundingPolicyState = "default" | "workflow" | "required" | "needs_configuration";

export const EVIDENCE_GROUNDING_POLICY_STATES: ReadonlyArray<{
  state: Exclude<EvidenceGroundingPolicyState, "needs_configuration">;
  label: string;
  stored: string;
  description: string;
}> = [
  {
    state: "default",
    label: "Default (workflow)",
    stored: "{}",
    description:
      "No explicit value: the evidence-grounded answer contract applies when the selected workflow requires sources or live evidence, or the agent type is configured as high-risk.",
  },
  {
    state: "workflow",
    label: "Workflow and agent type",
    stored: '{"mode": "workflow"}',
    description:
      "Same as the default, stored explicitly: only the selected workflow and the high-risk agent types decide.",
  },
  {
    state: "required",
    label: "Every turn",
    stored: '{"mode": "required"}',
    description:
      "Every turn in this Workspace obeys the evidence-grounded answer contract, plain chat included. The prompt's wording never decides.",
  },
];

export function evidenceGroundingPolicyState(config: unknown): EvidenceGroundingPolicyState {
  const root = config && typeof config === "object" ? (config as Record<string, unknown>) : {};
  if (!(EVIDENCE_GROUNDING_POLICY_KEY in root)) return "default";
  const section = root[EVIDENCE_GROUNDING_POLICY_KEY];
  if (!section || typeof section !== "object" || Array.isArray(section)) return "needs_configuration";
  const entries = section as Record<string, unknown>;
  if (Object.keys(entries).some((key) => key !== "mode")) return "needs_configuration";
  const mode = entries.mode;
  if (mode === undefined || mode === null) return "default";
  if (mode === "workflow" || mode === "required") return mode;
  return "needs_configuration";
}

export function evidenceGroundingPolicyPatch(state: EvidenceGroundingPolicyState) {
  const mode = state === "workflow" || state === "required" ? state : null;
  return { [EVIDENCE_GROUNDING_POLICY_KEY]: { mode } };
}
