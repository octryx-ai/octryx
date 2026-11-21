// The server has reauthorized this exact card. Never rebuild withheld source facts from chat/context.
import type { PayloadView } from "./workflowRunPayloadView";

const HEADINGS: Record<string, string> = {
  idea_frame: "Confirm the idea", research_plan: "Confirm the research plan",
  research_brief: "Confirm the research brief", spec: "Confirm the specification",
};

export function specificationPayloadView(payload: Record<string, unknown>): PayloadView | null {
  const kind = typeof payload.shows === "string" ? payload.shows : "";
  if (!Object.hasOwn(HEADINGS, kind)) return null;
  const output = payload.output;
  const record = output && typeof output === "object" && !Array.isArray(output)
    ? output as Record<string, unknown> : null;
  const missing = typeof payload.missing === "string" && payload.missing ? payload.missing : null;
  const available = record && record.schema_version === `${kind}/v1`
    && typeof record.version === "number" && Number.isInteger(record.version) && record.version > 0
    && typeof record.hash === "string" && /^sha256:[0-9a-f]{64}$/.test(record.hash);
  const base = { heading: HEADINGS[kind],
    blockers: Array.isArray(payload.blockers) ? payload.blockers.map(String) : [], testAlert: null };
  if (missing || !available) return { ...base, lines: [], text: null,
    missing: missing ?? "The current record is unavailable. Refresh the decision before confirming." };
  const lines = [`Record version ${record.version}`, `Record hash ${record.hash}`];
  if (kind === "research_plan") lines.push(
    "Whole-run budget thresholds are checked after each completed phase turn. A turn can overshoot; "
    + "these are not hard per-read caps or a guaranteed wall-clock timeout.",
  );
  // Shared React <pre> renders plain text: no nested scope/criteria/budget/evidence is hidden or truncated.
  return { ...base, lines, missing: null, text: JSON.stringify(record, null, 2) };
}
