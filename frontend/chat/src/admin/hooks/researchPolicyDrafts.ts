// Research policy drafts: the empty list payload and the spec JSON format/parse used by the editor.
import type { ResearchPolicyListPayload } from "../types/researchPolicyTypes";

export const EMPTY_POLICY_PAYLOAD: ResearchPolicyListPayload = {
  profiles: [],
  defaults: { default_profile_key: "" },
  diagnostics: { status: "valid", invalid_version_count: 0 },
};

export function formatSpec(spec: Record<string, unknown> | null | undefined) {
  return JSON.stringify(spec || {}, null, 2);
}

export function parseSpecDraft(value: string) {
  const parsed = JSON.parse(value) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Research policy spec must be a JSON object.");
  }
  return parsed as Record<string, unknown>;
}
