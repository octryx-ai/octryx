// The incident analysis settings per Workspace (B/D) and refusals in words. Pure: no requests, no React.
// The ServiceNow intake itself is set up in Work → Intake (`chat/work/intake/`).

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value.trim() : typeof value === "number" ? String(value) : "");

/** A refused intake request, in words. */
export function intakeErrorText(error: unknown, action: string, subject = "the ServiceNow intake"): string {
  const record = isRecord(error) ? error : null;
  if (record?.status === 404) return `This server does not offer ${subject} yet, or the Workspace is not visible to you.`;
  if (record?.status === 403) return `You may not ${action} (Workspace admin or owner needed).`;
  if (record?.status === 409 && record.code === "servicenow_intake_not_configured") return "Save the intake first.";
  if (record?.status === 409 && record.code === "servicenow_connection_not_configured") return "Connect ServiceNow under Automation → Connectors first.";
  if (record?.status === 422 && (record.field === "assignment_groups" || record.field === "services")) {
    const noun = record.field === "services" ? "services" : "assignment groups";
    return `Could not ${action}: the ${noun} must be valid names or sys_ids within the connector's limit (the intake may only narrow it).`;
  }
  const message = typeof record?.message === "string" && record.message ? record.message : "the request failed";
  return `Could not ${action}: ${message}.`;
}

// ---- analysis settings ---------------------------------------------------------------------------
//
// Backend (work_item_analysis/settings.py, Project.config.work_item_analysis):
//   GET/PUT /api/v1/secure-work/work-item-analysis-settings/{project_id} -> {project_id, model_policy, cost_cap_usd,
//   auto_analyze: {servicenow_new_incidents, jira_label}, ask_reporter, runner: governed|seat, max_output_tokens
//   (1024..32000, default 8192), source, can_edit}. PUT takes some or all keys; unknown keys are refused (422), so
//   only these are sent; model_policy and cost_cap_usd are sent back as loaded. `runner: seat`: each user analyses in
//   their own seat session (`octryx-claude analyze <KEY>`); the server never starts a run, not even an automatic one.

export type AnalysisRunner = "governed" | "seat";

export type AnalysisSettings = {
  servicenowNewIncidents: boolean;
  jiraLabelOn: boolean;
  jiraLabel: string;
  askReporter: boolean;
  runner: AnalysisRunner;
  // As typed; validated by analysisSettingsError.
  maxOutputTokens: string;
  modelPolicy: string | null;
  maxCostUsd: number | null;
  canEdit: boolean;
};

export const DEFAULT_JIRA_LABEL = "octryx";
export const MAX_OUTPUT_TOKENS_MIN = 1024;
export const MAX_OUTPUT_TOKENS_MAX = 32000;
export const MAX_OUTPUT_TOKENS_DEFAULT = 8192;
const LABEL = /^[^\s,]{1,64}$/;
const positive = (value: unknown) => (typeof value === "number" && value > 0 ? value : null);

export function readAnalysisSettings(payload: unknown): AnalysisSettings | null {
  const settings = isRecord(payload) && isRecord(payload.settings) ? payload.settings : payload;
  if (!isRecord(settings) || !isRecord(settings.auto_analyze)) return null;
  const label = text(settings.auto_analyze.jira_label);
  return {
    servicenowNewIncidents: settings.auto_analyze.servicenow_new_incidents === true,
    jiraLabelOn: Boolean(label),
    jiraLabel: label || DEFAULT_JIRA_LABEL,
    askReporter: settings.ask_reporter === true,
    runner: settings.runner === "seat" ? "seat" : "governed",
    maxOutputTokens: text(settings.max_output_tokens) || String(MAX_OUTPUT_TOKENS_DEFAULT),
    modelPolicy: text(settings.model_policy) || null,
    maxCostUsd: positive(settings.cost_cap_usd),
    canEdit: !isRecord(payload) || payload.can_edit !== false,
  };
}

export function analysisSettingsError(settings: AnalysisSettings): string | null {
  if (settings.jiraLabelOn && !LABEL.test(settings.jiraLabel.trim())) return "Enter one Jira label without spaces or commas (at most 64 characters).";
  const tokens = settings.maxOutputTokens.trim();
  if (!/^\d+$/.test(tokens) || Number(tokens) < MAX_OUTPUT_TOKENS_MIN || Number(tokens) > MAX_OUTPUT_TOKENS_MAX) {
    return `Enter the max output tokens as a whole number from ${MAX_OUTPUT_TOKENS_MIN} to ${MAX_OUTPUT_TOKENS_MAX}.`;
  }
  return null;
}

/** The complete settings object of a valid draft; the values not edited here are sent back as loaded. */
export function analysisSettingsPayload(settings: AnalysisSettings): Record<string, unknown> {
  return {
    model_policy: settings.modelPolicy,
    ...(settings.maxCostUsd !== null ? { cost_cap_usd: settings.maxCostUsd } : {}),
    auto_analyze: {
      servicenow_new_incidents: settings.servicenowNewIncidents,
      jira_label: settings.jiraLabelOn ? settings.jiraLabel.trim() : null,
    },
    ask_reporter: settings.askReporter,
    runner: settings.runner,
    max_output_tokens: Number(settings.maxOutputTokens.trim()),
  };
}
