// The two decisions a product owner takes in a delivery run:
// readiness ("is the ticket clear enough to build?") and the review decision ("ship or another round?").
// The server keeps one text answer per decision (`reason` of the change action); this module splits it into one
// field per question and per finding for the person, and joins the fields back into that one text.

import { WORKFLOW_RUNS_PATH } from "./workflowRunRequests";
import { type RunAction, type RunWaiting, type WorkflowRun } from "./workflowRunTypes";

export type DecisionFinding = {
  severity: string;
  file: string;
  line: number | null;
  fix: string;
  // What is wrong, in a line (the run view's open findings); "" when the review gave only the fix.
  summary?: string;
};

export type DecisionCard = {
  subject: "decisions" | "readiness";
  // Review decision only: "changes" or "pass"; readiness: null.
  verdict: string | null;
  heading: string;
  summary: string;
  findings: DecisionFinding[];
  questions: string[];
  // The agent's own note (readiness), shown as markdown below the fields.
  note: string;
};

const SEVERITY_ORDER = ["high", "medium", "low"];

function texts(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item ?? "").trim()).filter(Boolean) : [];
}

// A question the agent asked in its readiness note: a list item or numbered line that ends with "?".
export function questionsInNote(note: string): string[] {
  const found: string[] = [];
  for (const raw of note.split(/\r?\n/)) {
    const line = raw.trim();
    const item = line.match(/^(?:[-*+]|\d+[.)]|[A-Za-z][.)])\s+(.+)$/);
    const text = (item ? item[1] : "").replace(/\*\*/g, "").trim();
    if (text.endsWith("?") && text.length > 3) found.push(text);
  }
  return found;
}

const severityRank = (severity: string) => {
  const rank = SEVERITY_ORDER.indexOf(severity);
  return rank < 0 ? SEVERITY_ORDER.length : rank;
};

/** A review's findings as the cards show them, high first (then medium, low, anything else); not a list: none. */
export function readFindings(value: unknown): DecisionFinding[] {
  return (Array.isArray(value) ? value : [])
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item) => ({
      severity: String(item.severity ?? "").toLowerCase(),
      file: String(item.file ?? ""),
      line: typeof item.line === "number" ? item.line : Number(item.line) || null,
      fix: String(item.fix ?? ""),
      summary: String(item.summary ?? ""),
    }))
    .sort((a, b) => severityRank(a.severity) - severityRank(b.severity));
}

function severityCounts(findings: DecisionFinding[]): string {
  const counts = SEVERITY_ORDER.map((level) => [level, findings.filter((item) => item.severity === level).length] as const)
    .filter(([, count]) => count > 0)
    .map(([level, count]) => `${count} ${level}`);
  return counts.join(" · ");
}

export function decisionCard(waiting: RunWaiting | undefined): DecisionCard | null {
  if (!waiting || waiting.kind !== "awaiting_confirmation") return null;
  const payload = (waiting.payload ?? {}) as Record<string, unknown>;
  const subject = String(waiting.subject ?? payload.subject ?? "");
  if (subject === "decisions") {
    const output = (payload.output ?? {}) as Record<string, unknown>;
    const findings = readFindings(output.findings);
    const verdict = String(output.verdict ?? "") || null;
    const counts = severityCounts(findings);
    return {
      subject,
      verdict,
      heading: verdict === "changes" ? "Review: changes needed" : verdict === "pass" ? "Review: ready to ship" : "Review",
      summary: [counts, typeof output.summary === "string" ? output.summary : ""].filter(Boolean).join(" — "),
      findings,
      questions: texts(output.assumptions),
      note: "",
    };
  }
  if (subject === "readiness") {
    const note = typeof payload.text === "string" ? payload.text : "";
    const questions = questionsInNote(note);
    return {
      subject,
      verdict: null,
      heading: "Is the ticket ready to build?",
      summary: questions.length
        ? `The agent has ${questions.length} open question${questions.length === 1 ? "" : "s"}. Answer what you can.`
        : note.trim()
          ? "Read the agent's note, then start building or answer it."
          : "The agent's questions are in its last message in the chat. Answer them here, or start building as it is.",
      findings: [],
      questions,
      note,
    };
  }
  return null;
}

export function findingPlace(finding: DecisionFinding): string {
  const file = finding.file.split("/").pop() || finding.file;
  return finding.line ? `${file}:${finding.line}` : file;
}

export type DecisionAnswers = { findings: Record<number, string>; questions: Record<number, string>; other: string };

export const EMPTY_ANSWERS: DecisionAnswers = { findings: {}, questions: {}, other: "" };

// The one text the change action posts: numbered points the reviewer checks one by one (PO_ANSWERS_RULE).
export function composeAnswer(card: DecisionCard, answers: DecisionAnswers): string {
  const lines: string[] = [];
  card.findings.forEach((finding, index) => {
    const text = (answers.findings[index] ?? "").trim();
    if (text) lines.push(`${lines.length + 1}. Finding ${finding.file}${finding.line ? `:${finding.line}` : ""} [${finding.severity}]: ${text}`);
  });
  card.questions.forEach((question, index) => {
    const text = (answers.questions[index] ?? "").trim();
    if (text) lines.push(`${lines.length + 1}. ${question} → ${text}`);
  });
  const other = answers.other.trim();
  if (other) lines.push(`${lines.length + 1}. ${other}`);
  if (!lines.length && card.verdict === "changes" && card.findings.length)
    return "Fix every finding as the reviewer proposes.";
  return lines.join("\n");
}

export function answeredCount(card: DecisionCard, answers: DecisionAnswers): number {
  return card.questions.filter((_, index) => (answers.questions[index] ?? "").trim()).length;
}

// The primary action follows the decision: review wants changes → another round; otherwise confirm.
export function decisionPrimary(run: Pick<WorkflowRun, "actions" | "waiting">): RunAction | null {
  const card = decisionCard(run.waiting);
  if (!card) return null;
  const confirm = run.actions.find((action) => action.key === "confirm") ?? null;
  const change = run.actions.find((action) => action.key === "change") ?? null;
  if (card.subject === "decisions" && card.verdict === "changes") return change ?? confirm;
  return confirm ?? change;
}

// ---- What the system tests saw (run card mock) ------------------------------------------------
// The screenshots of the run's last pass, kept on the server; the card shows a few, the rest one click away.

export type RunScreen = { name: string; media_type: string; size: number; node_id: string };

export const SCREENS_PREVIEW = 4;

export function runScreensPath(runId: string): string {
  return `${WORKFLOW_RUNS_PATH}/${encodeURIComponent(runId)}/screens`;
}

export function runScreenUrl(runId: string, name: string): string {
  return `${runScreensPath(runId)}/${encodeURIComponent(name)}`;
}

export type ScreensView = { heading: string; shown: RunScreen[]; more: string | null };

/** The card's screenshot section; null without screenshots (the section is then not shown at all). */
export function screensView(screens: RunScreen[] | null | undefined, showAll: boolean): ScreensView | null {
  const list = screens ?? [];
  if (!list.length) return null;
  const folded = !showAll && list.length > SCREENS_PREVIEW;
  return {
    heading: `What the system tests saw · ${list.length} screenshot${list.length === 1 ? "" : "s"}`,
    shown: folded ? list.slice(0, SCREENS_PREVIEW) : list,
    more: folded ? `Show all ${list.length}` : null,
  };
}

// Actions the card itself shows; "stop" (with its reason) goes to the ⋯ menu like abort.
export const CARD_ACTION_KEYS = ["confirm", "change"];

export function isStopLike(action: RunAction): boolean {
  return action.tone === "danger" || action.key === "stop";
}

// Labels that say what happens next on this card; other cards keep the server's labels.
export function decisionLabel(card: DecisionCard, action: RunAction): string {
  if (card.subject === "decisions") {
    if (action.key === "change") return "Send answers · start another round";
    if (action.key === "confirm") return card.verdict === "changes"
      ? "Ship anyway: push and open the pull request" : "Ship it: push and open the pull request";
  }
  if (card.subject === "readiness") {
    if (action.key === "change") return "Send answers, then build";
    if (action.key === "confirm") return "Start building as it is";
  }
  return action.label;
}

