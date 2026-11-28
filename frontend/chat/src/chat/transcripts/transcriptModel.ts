import { count, isRecord, text } from "./transcriptValues";

export const RETENTION_MIN = 1;
export const RETENTION_MAX = 3650;
export const RETENTION_DEFAULT = 30;

export type TranscriptSettings = { enabled: boolean; retentionDays: number };
export type TranscriptSettingsAnswer = TranscriptSettings & { source: "default" | "workspace"; canEdit: boolean };

export function readTranscriptSettings(payload: unknown): TranscriptSettingsAnswer | null {
  if (!isRecord(payload) || !isRecord(payload.session_transcripts)) return null;
  const raw = payload.session_transcripts;
  const days = count(raw.retention_days);
  if (typeof raw.enabled !== "boolean" || days === null) return null;
  return {
    enabled: raw.enabled,
    retentionDays: days,
    source: payload.source === "workspace" ? "workspace" : "default",
    canEdit: payload.can_edit === true,
  };
}

export function retentionProblem(days: number): string | null {
  if (!Number.isInteger(days) || days < RETENTION_MIN || days > RETENTION_MAX) {
    return `Enter whole days from ${RETENTION_MIN} to ${RETENTION_MAX}.`;
  }
  return null;
}

export function settingsChangeBody(saved: TranscriptSettings, draft: TranscriptSettings): Record<string, unknown> {
  return {
    ...(draft.enabled !== saved.enabled ? { enabled: draft.enabled } : {}),
    ...(draft.retentionDays !== saved.retentionDays ? { retention_days: draft.retentionDays } : {}),
  };
}

export type SettingsErrors = { enabled?: string; retentionDays?: string; general?: string };

const CODE_TEXT: Record<string, string> = {
  invalid_retention_days: `Enter whole days from ${RETENTION_MIN} to ${RETENTION_MAX}.`,
  invalid_flag: "The switch must be on or off.",
  unknown_field: "The server does not know this setting.",
};

export function settingsSaveErrors(status: number, body: unknown): SettingsErrors {
  const detail = isRecord(body) ? body.detail : null;
  if (status === 422 && isRecord(detail) && Array.isArray(detail.errors)) {
    const errors: SettingsErrors = {};
    for (const error of detail.errors.filter(isRecord)) {
      const words = CODE_TEXT[text(error.code)] ?? "This value was refused.";
      const field = text(error.field).split(".").pop();
      if (field === "retention_days") errors.retentionDays = words;
      else if (field === "enabled") errors.enabled = words;
      else errors.general = `Not saved: ${words}`;
    }
    if (Object.keys(errors).length) return errors;
  }
  if (status === 403) return { general: "Not saved: only Workspace admins and owners can change this." };
  if (status === 404) return { general: "Not saved: this Workspace was not found, or you are not a member." };
  return { general: "Not saved: the request failed." };
}

export type TranscriptStream = { stream: string; lines: number; firstLine: number; lastLine: number };

export type TranscriptItem = {
  sessionId: string;
  workflowRunId: string | null;
  deviceJobId: string | null;
  firstAt: string | null;
  lastAt: string | null;
  bytesStored: number;
  streams: TranscriptStream[];
};

export type TranscriptFilter = { sessionId?: string | null; workflowRunId?: string | null; deviceJobId?: string | null };

function readStreams(value: unknown): TranscriptStream[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord).flatMap((raw) => {
    const stream = text(raw.stream);
    if (!stream) return [];
    return [{ stream, lines: count(raw.lines) ?? 0, firstLine: count(raw.first_line) ?? 1, lastLine: count(raw.last_line) ?? 0 }];
  });
}

export function readTranscriptList(payload: unknown): TranscriptItem[] | null {
  if (!isRecord(payload) || !Array.isArray(payload.items)) return null;
  return payload.items.filter(isRecord).flatMap((raw) => {
    const sessionId = text(raw.session_id);
    if (!sessionId) return [];
    return [{
      sessionId,
      workflowRunId: text(raw.workflow_run_id) || null,
      deviceJobId: text(raw.device_job_id) || null,
      firstAt: text(raw.first_at) || null,
      lastAt: text(raw.last_at) || null,
      bytesStored: count(raw.bytes_stored) ?? 0,
      streams: readStreams(raw.streams),
    }];
  });
}

/** The query string of the list request; "" when no filter is set (a page never asks for the whole list). */
export function transcriptFilterQuery(filter: TranscriptFilter): string {
  const params = new URLSearchParams();
  if (filter.sessionId) params.set("session_id", filter.sessionId);
  if (filter.workflowRunId) params.set("workflow_run_id", filter.workflowRunId);
  if (filter.deviceJobId) params.set("device_job_id", filter.deviceJobId);
  return params.toString();
}

export const MAIN_STREAM = "main";

export function streamLabel(stream: string): string {
  if (stream === MAIN_STREAM) return "Main";
  const id = stream.replace(/^agent-/, "");
  return `Subagent ${id.slice(0, 7)}`;
}

export function orderStreams(streams: TranscriptStream[]): TranscriptStream[] {
  return [...streams.filter((entry) => entry.stream === MAIN_STREAM), ...streams.filter((entry) => entry.stream !== MAIN_STREAM)];
}

export const PAGE_LIMIT = 200;

export type TranscriptLine = { line: number; entry: unknown };
export type TranscriptPage = { lines: TranscriptLine[]; next: number | null; streams: TranscriptStream[] };

export function readTranscriptPage(payload: unknown): TranscriptPage | null {
  if (!isRecord(payload) || !Array.isArray(payload.lines)) return null;
  const lines = payload.lines.filter(isRecord).flatMap((raw) => {
    const line = count(raw.line);
    return line === null ? [] : [{ line, entry: raw.entry }];
  });
  const next = count(payload.next_from_line);
  return { lines, next: next !== null && next > 0 ? next : null, streams: readStreams(payload.streams) };
}

export type StreamPaging = {
  lines: TranscriptLine[];
  next: number | null;
  loading: boolean;
  problem: "missing" | "failed" | null;
};

export function initialPaging(firstLine = 1): StreamPaging {
  return { lines: [], next: firstLine, loading: false, problem: null };
}

export function nextRequest(paging: StreamPaging): { fromLine: number; limit: number } | null {
  if (paging.loading || paging.next === null || paging.problem === "missing") return null;
  return { fromLine: paging.next, limit: PAGE_LIMIT };
}

export function appendPage(paging: StreamPaging, page: TranscriptPage): StreamPaging {
  const seen = new Set(paging.lines.map((entry) => entry.line));
  const added = page.lines.filter((entry) => !seen.has(entry.line));
  return { lines: [...paging.lines, ...added], next: page.next, loading: false, problem: null };
}

export function pagingFailed(paging: StreamPaging, status: number | undefined): StreamPaging {
  return { ...paging, loading: false, problem: status === 404 ? "missing" : "failed" };
}


// "[redacted]", "[REDACTED]" and "[redacted: output of a secret command or credential file]".
const REDACTION = /\[redacted(?::[^\]\n]{0,200})?\]/gi;

export type TextSegment = { text: string; redacted: boolean };

export function redactionSegments(value: string): TextSegment[] {
  const segments: TextSegment[] = [];
  let last = 0;
  for (const match of value.matchAll(REDACTION)) {
    const start = match.index ?? 0;
    if (start > last) segments.push({ text: value.slice(last, start), redacted: false });
    segments.push({ text: match[0], redacted: true });
    last = start + match[0].length;
  }
  if (last < value.length) segments.push({ text: value.slice(last), redacted: false });
  return segments;
}

export function hasRedaction(value: string): boolean {
  REDACTION.lastIndex = 0;
  const found = REDACTION.test(value);
  REDACTION.lastIndex = 0;
  return found;
}
