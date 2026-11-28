import { safeHttpUrl } from "../workItemDetailModel";
import type { WorkItem } from "../workItemTypes";
import { readReporterQuestion, type ReporterQuestion } from "../../../admin/components/securityControls/securityControlsModel";

// The server never starts a seat-runner analysis itself; it answers with the command instead.
// The analysis is agent-written data: it never changes the item.

export type AnalysisState = "none" | "running" | "done" | "failed" | "needs_configuration" | "denied" | "skipped";
const STATUS_STATE: Record<string, AnalysisState> = {
  none: "none",
  running: "running",
  queued: "running",
  succeeded: "done",
  done: "done",
  failed: "failed",
  needs_configuration: "needs_configuration",
  denied: "denied",
  skipped: "skipped",
};

export const SEAT_RUNNER_CODE = "analysis_runs_in_seat";

export type Citation = { label: string; url: string | null; verified: boolean | null };
export type EvidenceLine = { text: string; citation: Citation | null };
export type SimilarTicket = { number: string; title: string; url: string | null; verified: boolean | null };

export type IncidentAnalysis = {
  summary: string;
  impact: string;
  likelyCause: string;
  confidence: string;
  affectedComponents: string[];
  evidence: EvidenceLine[];
  similarTickets: SimilarTicket[];
  nextSteps: string[];
  openQuestions: string[];
};

export type AnalysisView = {
  id: string | null;
  state: AnalysisState;
  reason: string | null;
  detail: string | null;
  runner: "governed" | "seat" | null;
  model: string | null;
  command: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  analysis: IncidentAnalysis | null;
  reused: boolean;
  reporterQuestion: ReporterQuestion | null;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value.trim() : typeof value === "number" ? String(value) : "");
const texts = (value: unknown) => (Array.isArray(value) ? value.map(text).filter(Boolean) : []);
const flag = (value: unknown) => (typeof value === "boolean" ? value : null);

export function citationOf(value: unknown, verified: unknown = null): Citation | null {
  if (!isRecord(value)) return null;
  const label = [text(value.title), text(value.locator)].filter(Boolean).join(", ");
  if (!label) return null;
  return { label, url: safeHttpUrl(value.url), verified: flag(verified) };
}

export function readAnalysis(value: unknown): IncidentAnalysis | null {
  if (!isRecord(value)) return null;
  const cause = isRecord(value.likely_cause) ? value.likely_cause : { text: value.likely_cause };
  const analysis: IncidentAnalysis = {
    summary: text(value.summary),
    impact: text(value.impact),
    likelyCause: text(cause.text),
    confidence: text(cause.confidence),
    affectedComponents: texts(value.affected_components),
    evidence: (Array.isArray(value.evidence) ? value.evidence : [])
      .map((entry): EvidenceLine | null => {
        if (!isRecord(entry)) return null;
        const line = text(entry.claim);
        return line ? { text: line, citation: citationOf(entry.source, entry.verified) ?? citationOf(entry, entry.verified) } : null;
      })
      .filter((entry): entry is EvidenceLine => entry !== null),
    similarTickets: (Array.isArray(value.similar_tickets) ? value.similar_tickets : [])
      .filter(isRecord)
      .map((entry) => ({ number: text(entry.key), title: text(entry.why), url: safeHttpUrl(entry.url), verified: flag(entry.verified) }))
      .filter((entry) => entry.number),
    nextSteps: texts(value.next_steps),
    openQuestions: texts(value.open_questions),
  };
  return analysis.summary || analysis.evidence.length ? analysis : null;
}

export function readAnalysisView(payload: unknown): AnalysisView | null {
  if (!isRecord(payload)) return null;
  const state = STATUS_STATE[text(payload.status)];
  if (!state) return null;
  return {
    id: text(payload.id) || null,
    state,
    reason: text(payload.error_code) || null,
    detail: text(payload.error_detail) || null,
    runner: payload.runner === "seat" || payload.runner === "governed" ? payload.runner : null,
    model: text(payload.model) || null,
    command: text(payload.command) || null,
    startedAt: text(payload.created_at) || null,
    finishedAt: text(payload.finished_at) || null,
    analysis: readAnalysis(payload.analysis),
    reused: payload.reused === true,
    reporterQuestion: readReporterQuestion(payload.reporter_question),
  };
}

export const NO_ANALYSIS: AnalysisView = {
  id: null, state: "none", reason: null, detail: null, runner: null, model: null, command: null, startedAt: null, finishedAt: null,
  analysis: null, reused: false, reporterQuestion: null,
};

export function latestAnalysisNote(item: Pick<WorkItem, "source_fields">): { at: string | null; text: string } | null {
  const notes = (item.source_fields as Record<string, unknown> | undefined)?.platform_notes;
  if (!Array.isArray(notes)) return null;
  for (let index = notes.length - 1; index >= 0; index -= 1) {
    const note = notes[index];
    if (isRecord(note) && text(note.kind) === "analysis" && text(note.note)) return { at: text(note.at) || null, text: text(note.note) };
  }
  return null;
}

export const ANALYSIS_POLL_MS = 5_000;

export function analysisInProgress(view: AnalysisView | null): boolean {
  return view?.state === "running";
}

export function analysisStateText(view: AnalysisView): string {
  const why = view.reason ? `: ${reasonText(view.reason)}` : ".";
  if (view.state === "running") return "Analysis running…";
  if (view.state === "done") return view.reused ? "Analysis done (already up to date for this item version)." : "Analysis done.";
  if (view.state === "failed") return `The analysis failed${why}`;
  if (view.state === "needs_configuration") return `The analysis needs configuration${why}`;
  if (view.state === "denied") return `The analysis was refused${why}`;
  if (view.state === "skipped" && view.reason === SEAT_RUNNER_CODE && view.command) return `Not analysed${why}. Run: ${view.command}`;
  if (view.state === "skipped") return `Not analysed${why}`;
  return "No analysis yet.";
}

export function analysisCauseText(view: AnalysisView): string | null {
  if (!view.detail || view.state === "done" || view.state === "running" || view.state === "none") return null;
  return `Cause: ${view.detail}`;
}

export function analysisRunnerText(view: AnalysisView): string | null {
  if (view.runner !== "seat") return null;
  return `Ran in a seat session${view.model ? ` (model ${view.model})` : ""}.`;
}

// The backend's key rule for a printable command (work_item_analysis.runner._COMMAND_KEY).
const COMMAND_KEY = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

export function seatCommand(sourceKey: string | null | undefined): string | null {
  const key = String(sourceKey ?? "");
  return COMMAND_KEY.test(key) ? `octryx-claude analyze ${key}` : null;
}

export function seatCommandToShow(view: AnalysisView | null, runner: string | null, sourceKey: string): string | null {
  if (view?.reason === SEAT_RUNNER_CODE && view.command) return view.command;
  return runner === "seat" ? seatCommand(sourceKey) : null;
}

const REASON_TEXT: Record<string, string> = {
  model_policy_unresolved: "no model policy is set for the analysis in this Workspace",
  item_closed: "closed items are not analysed automatically",
  auto_rate_limited: "this item was analysed automatically within the last 24 hours",
  analysis_slot_busy: "an analysis of this item is already running",
  work_item_without_workspace: "the item belongs to no Workspace",
  analysis_not_json: "the model did not answer with the analysis format",
  analysis_invalid: "the model's analysis was incomplete",
  analysis_uncited: "the analysis cited nothing the tools had shown",
  analysis_runtime_error: "the analysis run stopped with an error",
  budget_exceeded: "the analysis reached its cost cap for this Workspace",
  analysis_runs_in_seat: "this Workspace analyses in each user's own seat session, not on the server",
};

export function reasonText(reason: string | null): string {
  if (!reason) return "";
  return REASON_TEXT[reason] ?? `refused (${reason})`;
}

export function analyzeRefusalText(error: unknown): string {
  const record = isRecord(error) ? error : null;
  if (record?.status === 404) return "This server does not offer the incident analysis yet.";
  if (record?.status === 403) return "You may not start an analysis in this Workspace.";
  const code = typeof record?.code === "string" ? record.code : null;
  if (code && REASON_TEXT[code]) return `Not started: ${REASON_TEXT[code]}.`;
  const message = typeof record?.message === "string" && record.message ? record.message : "the request failed";
  return `Not started: ${message}.`;
}

export type WorknotePreview = { available: true; number: string; text: string } | { available: false; reason: string };

const WORKNOTE_REASON_TEXT: Record<string, string> = {
  servicenow_worknote_disabled: "work notes to ServiceNow are switched off for this connector",
  servicenow_worknote_not_configured: "the work-note settings of the ServiceNow connector are incomplete",
  servicenow_worknote_not_a_servicenow_item: "only ServiceNow items take work notes",
  servicenow_worknote_no_analysis_note: "there is no analysis to send yet",
  servicenow_worknote_already_posted: "this analysis was already sent as a work note",
  servicenow_worknote_secret_detected: "the summary contains secret material and is never sent",
  servicenow_worknote_failed: "ServiceNow did not accept the work note",
};

export function readWorknotePreview(payload: unknown): WorknotePreview | null {
  if (!isRecord(payload) || text(payload.state) !== "needs_confirmation" || !isRecord(payload.preview)) return null;
  const preview = payload.preview;
  const body = text(preview.text);
  return body ? { available: true, number: text(preview.number), text: body } : null;
}

export function worknoteRefusalText(error: unknown): string {
  const record = isRecord(error) ? error : null;
  if (record?.status === 404 && !record.code) return "This server does not offer work notes to ServiceNow yet";
  if (record?.status === 403) return "You may not send work notes in this Workspace";
  const code = typeof record?.code === "string" ? record.code : "";
  const message = typeof record?.message === "string" && record.message ? record.message : "the request failed";
  return WORKNOTE_REASON_TEXT[code] ? capitalize(WORKNOTE_REASON_TEXT[code]) : message;
}

const capitalize = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);
