// Live validation in the browser with @cedar-policy/cedar-wasm, the same Cedar version (4.12) the server uses.
// The 4 MB module loads only when the policy editor opens. If it cannot load, the editor says so and keeps working:
// the server validates every save anyway.

import type { CedarVocabulary } from "./cedarLanguage";
import { vocabularyOf } from "./cedarLanguage";

export type LiveIssue = { message: string; start: number; end: number; severity: "error" | "warning" };
export type LiveValidation = { available: boolean; issues: LiveIssue[] };

type CedarWasm = {
  validate(call: { schema: string; policies: { staticPolicies: string } }): {
    type: "success" | "failure";
    errors?: DetailedError[];
    validationErrors?: { policyId: string; error: DetailedError }[];
    validationWarnings?: { policyId: string; error: DetailedError }[];
  };
  schemaToJson(schema: string): { type: "success" | "failure"; json?: unknown };
};
type DetailedError = { message: string; help: string | null; sourceLocations?: { start: number; end: number }[] };

let loading: Promise<CedarWasm | null> | null = null;

/** Loads and initialises the web build once; `null` when the browser cannot run it. */
export function loadCedarWasm(): Promise<CedarWasm | null> {
  if (!loading) {
    loading = import("@cedar-policy/cedar-wasm/web")
      .then(async (module) => {
        await module.default();
        return module as unknown as CedarWasm;
      })
      .catch(() => null);
  }
  return loading;
}

function issue(error: DetailedError, severity: LiveIssue["severity"], length: number): LiveIssue {
  const location = error.sourceLocations?.[0];
  const start = location ? Math.max(0, Math.min(location.start, length)) : 0;
  const end = location ? Math.max(start, Math.min(location.end, length)) : Math.min(length, 1);
  const help = error.help ? ` (${error.help})` : "";
  return { message: `${error.message}${help}`, start, end, severity };
}

/** Parse and schema errors of `policies`, positioned by character offset. */
export function issuesOf(wasm: CedarWasm, schema: string, policies: string): LiveIssue[] {
  const answer = wasm.validate({ schema, policies: { staticPolicies: policies } });
  if (answer.type === "failure") return (answer.errors ?? []).map((error) => issue(error, "error", policies.length));
  return [
    ...(answer.validationErrors ?? []).map((item) => issue(item.error, "error", policies.length)),
    ...(answer.validationWarnings ?? []).map((item) => issue(item.error, "warning", policies.length)),
  ];
}

export async function validateLive(schema: string, policies: string): Promise<LiveValidation> {
  const wasm = await loadCedarWasm();
  if (!wasm) return { available: false, issues: [] };
  try {
    return { available: true, issues: issuesOf(wasm, schema, policies) };
  } catch {
    return { available: false, issues: [] };
  }
}

export async function schemaVocabulary(schema: string): Promise<CedarVocabulary | null> {
  const wasm = await loadCedarWasm();
  if (!wasm) return null;
  const answer = wasm.schemaToJson(schema);
  return answer.type === "success" ? vocabularyOf(answer.json) : null;
}
