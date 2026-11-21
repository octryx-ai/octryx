// What a run confirmation shows: the typed payload the decision is bound to, as heading and lines.
import { specificationPayloadView } from "./specificationPayloadView";
import { documentationContractLines, publishProvePayload } from "./publishProveView";
import type { RunWaiting } from "./workflowRunTypes";

// What a confirmation shows: the typed payload the decision is bound to (its hash travels with "confirm").
export type PayloadView = {
  heading: string;
  lines: string[];
  blockers: string[];
  missing: string | null;
  text: string | null;
  testAlert: string | null;
};

export const TEST_ALERT_TEXT =
  "Started by a test alert: there is no real incident behind this run.";

const SUBJECT_HEADINGS: Record<string, string> = {
  test_contract: "These tests must pass",
  ticket_draft: "Ticket draft",
  reproduction: "Reproduction",
  retry_choice: "How to go on",
  advance: "Go to the next phase",
  questions: "Questions for the ticket",
};

// A confirmation shows the page body as plain text: the storage markup is never rendered as HTML.
export function storageText(body: string): string {
  return body
    .replace(/<(br|\/p|\/h[1-6]|\/li|\/tr)\s*\/?>/gi, "\n")
    .replace(/<[^>]*>/g, "")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

// A recorded artefact a confirmation shows (``shows``): its text fields and lists, one line each.
function shownLines(output: unknown): string[] {
  if (!output || typeof output !== "object") return [];
  const lines: string[] = [];
  for (const [key, value] of Object.entries(output as Record<string, unknown>)) {
    if (key === "hash" || key === "version" || key === "at" || value === null || value === "") continue;
    const label = key.replace(/_/g, " ");
    // The review card (ticket delivery): one line per finding and per open assumption, to answer them one by one.
    if (key === "findings" && Array.isArray(value)) {
      for (const item of value as Array<Record<string, unknown>>) {
        lines.push(`Finding ${String(item.file ?? "")}:${String(item.line ?? "")} [${String(item.severity ?? "")}] ${String(item.fix ?? "")}`);
      }
      continue;
    }
    if (key === "assumptions" && Array.isArray(value)) {
      value.forEach((item, index) => lines.push(`Open question ${index + 1}: ${String(item)}`));
      continue;
    }
    if (typeof value === "boolean") lines.push(`${label}: ${value ? "yes" : "no"}`);
    else if (Array.isArray(value)) {
      const items = value.map((item) => (typeof item === "object" ? JSON.stringify(item) : String(item)));
      if (items.length) lines.push(`${label}: ${items.join("; ")}`);
    } else if (typeof value !== "object") lines.push(`${label}: ${String(value)}`);
  }
  return lines;
}

export function payloadView(waiting: RunWaiting): PayloadView | null {
  if (!waiting || !["awaiting_confirmation", "functional_acceptance"].includes(waiting.kind)) return null;
  const payload = (waiting.payload ?? {}) as Record<string, unknown>;
  const specification = specificationPayloadView(payload);
  if (specification) return { ...specification, testAlert: payload.test_alert === true ? TEST_ALERT_TEXT : null };
  const subject = String(waiting.subject ?? payload.subject ?? "");
  const s1 = publishProvePayload(subject, payload);
  if (s1) return { ...s1, text: subject === "publication" && typeof payload.body === "string"
    ? storageText(payload.body) : s1.text };
  const criteria = Array.isArray(payload.acceptance_criteria)
    ? (payload.acceptance_criteria as Array<Record<string, unknown>>)
    : [];
  const lines = criteria.map((item) => {
    const head = `${String(item.id ?? "")}: ${String(item.text ?? "")}`;
    if (item.manual_only === true) {
      return `${head} — manual (${String(item.manual_reason ?? "")}); confirming takes it over`;
    }
    const commands = Array.isArray(item.validation_commands)
      ? (item.validation_commands as unknown[]).map(String)
      : [];
    // Each test with its role: new (fails before the change) or regression (keeps passing).
    const roles =
      item.test_roles && typeof item.test_roles === "object" ? (item.test_roles as Record<string, unknown>) : {};
    const tests = Array.isArray(item.tests)
      ? (item.tests as unknown[]).map(String).map((id) => (roles[id] ? `${id} (${String(roles[id])})` : id))
      : [];
    return `${head}${tests.length ? ` — tests ${tests.join(", ")}` : ""}${commands.length ? ` — ${commands.join(", ")}` : ""}`;
  });
  if (subject === "test_contract" && payload.change_plan_id) {
    const hash = String(payload.plan_hash ?? "").replace(/^sha256:/, "").slice(0, 12);
    lines.unshift(`Change plan v${String(payload.version ?? "")}${hash ? ` · ${hash}` : ""}`);
  }
  for (const question of strings(payload.open_questions)) lines.push(`Open question: ${question}`);
  if (subject === "reproduction") {
    const tests = strings(payload.tests);
    if (tests.length) lines.push(`Reproduced by ${tests.join(", ")}`);
    if (payload.symptom) lines.push(`Symptom: ${String(payload.symptom)}`);
    const failing = Array.isArray(payload.failing_tests)
      ? (payload.failing_tests as Array<Record<string, unknown>>).map((item) => String(item.id ?? ""))
      : [];
    if (failing.length) lines.push(`Failing in the last test run: ${failing.join(", ")}`);
  }
  if (subject === "advance") {
    if (payload.ticket_key) lines.push(`Ticket ${String(payload.ticket_key)}`);
    if (payload.branch) lines.push(`Branch ${String(payload.branch)}`);
  }
  lines.push(...documentationContractLines(payload.documentation_contract), ...shownLines(payload.output));
  return {
    heading: SUBJECT_HEADINGS[subject] ?? "Confirm",
    lines,
    blockers: Array.isArray(payload.blockers)
      ? (payload.blockers as unknown[]).map(String)
      : [],
    missing: typeof payload.missing === "string" ? payload.missing : null,
    text: typeof payload.text === "string" && payload.text ? payload.text : null,
    testAlert: payload.test_alert === true ? TEST_ALERT_TEXT : null,
  };
}
