const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");
const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;
const errorCode = (error: unknown) => (isRecord(error) && typeof error.code === "string" ? error.code : "");
const errorStatus = (error: unknown) => (isRecord(error) && typeof error.status === "number" ? error.status : 0);

export function newStartsHeld(preview: unknown): boolean {
  return isRecord(preview) && preview.new_starts_held === true;
}

export function resumeBody(workspaceId: string, reason: string): Record<string, string> {
  return workspaceId ? { workspace_id: workspaceId, reason: reason.trim() } : { reason: reason.trim() };
}

export type Hold = { scope: "platform" | "workspace"; by: string; at: string | null; reason: string };

export function readHold(preview: unknown): Hold | null {
  if (!isRecord(preview) || !isRecord(preview.hold)) return null;
  const scope = preview.held_by === "platform" || preview.held_by === "workspace" ? preview.held_by : null;
  if (!scope) return null;
  const by = isRecord(preview.hold.by) ? text(preview.hold.by.name) : "";
  const reason = text(preview.hold.reason);
  return { scope, by, at: text(preview.hold.at) || null, reason };
}

export function holdByText(hold: Hold, workspaceName: string): string {
  const where = hold.scope === "platform" ? "the whole platform" : workspaceName || "this Workspace";
  return `Stopped for ${where}${hold.by ? ` by ${hold.by}` : ""}`;
}

// Never a Workspace resume under a platform hold: the server would answer 409.
export function resumeOffer(hold: Hold | null, workspaceId: string, isPlatformAdmin: boolean): "resume" | "platform" | "none" {
  if (hold?.scope !== "platform" || !workspaceId) return "resume";
  return isPlatformAdmin ? "platform" : "none";
}

export const PLATFORM_HOLD_TEXT = "This is a platform stop: a Workspace resume cannot lift it, only a resume of the whole platform.";

export function heldText(workspaceName: string): string {
  const where = workspaceName ? `in ${workspaceName}` : "on the whole platform";
  return `An emergency stop holds every new run ${where}: schedules and webhook Actions start nothing until an admin resumes.`;
}

// Still held after a resume means a platform stop holds this Workspace too.
export function resumeResultText(payload: unknown, workspaceName: string): string {
  const where = workspaceName ? `in ${workspaceName}` : "on the platform";
  if (isRecord(payload) && payload.new_starts_held === true) {
    return `This Workspace's own stop is lifted, but a platform stop still holds new starts ${where}.`;
  }
  return `New starts run again ${where}. Paused runs stay paused until each is continued from its page.`;
}

const RESUME_CODE_TEXT: Record<string, string> = {
  not_stopped: "Nothing to resume here: a stop of this scope does not hold new starts. A platform stop is lifted from the platform view.",
  reason_required: "Say why new starts may run again; the reason goes into the audit log.",
  workspace_admin_required: "Only this Workspace's admins can resume it.",
  platform_admin_required: "Only platform admins can resume the whole platform.",
  admin_required: "Only admins can resume new starts.",
  workspace_id_invalid: "The Workspace was not understood. Reload the page and try again.",
};

export function resumeRefusalText(error: unknown): string {
  const known = RESUME_CODE_TEXT[errorCode(error)];
  if (known) return known;
  if (errorStatus(error) === 403) return "You may not resume new starts here.";
  const message = error instanceof Error && error.message ? error.message : "the request failed";
  return `Not resumed: ${message}`;
}

export type ReporterQuestion =
  | { state: "proposed"; questions: number }
  | { state: "posted"; questions: number; at: string | null }
  | { state: "skipped" | "failed"; reason: string };

export function readReporterQuestion(value: unknown): ReporterQuestion | null {
  if (!isRecord(value)) return null;
  const count = typeof value.questions === "number" && value.questions >= 0 ? value.questions : 0;
  const state = text(value.state);
  if (state === "proposed") return { state, questions: count };
  if (state === "posted") return { state, questions: count, at: text(value.at) || null };
  if (state === "skipped" || state === "failed") return { state, reason: text(value.reason) };
  return null;
}

export const askReporterPath = (workItemId: string, analysisId: string) =>
  `/api/v1/secure-work/work-items/${encodeURIComponent(workItemId)}/analyses/${encodeURIComponent(analysisId)}/ask-reporter`;

export function canSendQuestions(question: ReporterQuestion | null, openQuestions: number): boolean {
  return question?.state === "proposed" && openQuestions > 0;
}

const SKIP_TEXT: Record<string, string> = {
  no_open_questions: "the analysis has no open questions",
  ask_reporter_off: "asking the reporter is switched off for this Workspace",
  not_a_jira_item: "only Jira items take reporter questions",
  no_workflow: "the item has no workflow",
  jira_write_back_disabled: "the item's workflow does not write back to Jira",
  jira_mapping_not_synced: "the item's current state does not sync back to Jira",
  already_posted: "the questions were already posted",
  scope_not_allowed: "the issue is outside the Jira projects this connection may write to",
  jira_not_configured: "the Jira connection is not configured",
  reporter_unresolved: "the reporter could not be found in Jira",
  secret_detected: "the questions contain secret material and are never posted",
  nothing_proposed: "there are no proposed questions to send",
};

export function skipReasonText(reason: string): string {
  if (SKIP_TEXT[reason]) return SKIP_TEXT[reason];
  const http = /^jira_http_(\d{3})$/.exec(reason);
  if (http) return http[1].startsWith("5") ? `Jira did not answer (HTTP ${http[1]})` : `Jira answered with error ${http[1]}`;
  return reason ? "the questions could not be posted to Jira" : "the server gave no reason";
}

export function reporterQuestionText(question: ReporterQuestion | null): string | null {
  if (!question) return null;
  if (question.state === "proposed") {
    return `Proposed by an automatic analysis: nothing was posted. ${plural(question.questions, "question waits", "questions wait")} for a person to send ${question.questions === 1 ? "it" : "them"}.`;
  }
  if (question.state === "posted") return `Sent to the reporter in Jira (${plural(question.questions, "question", "questions")}).`;
  if (question.state === "failed") return `Not sent: ${skipReasonText(question.reason)}.`;
  return `Not sent: ${skipReasonText(question.reason)}.`;
}

export type AskReporterAnswer = { sent: boolean; attempt: string | null; question: ReporterQuestion | null };

export function readAskReporterAnswer(payload: unknown): AskReporterAnswer {
  const body = isRecord(payload) ? payload : {};
  const question = readReporterQuestion(body.reporter_question);
  const sent = body.sent === true || (body.sent === undefined && question?.state === "posted");
  const attempt = isRecord(body.attempt) ? body.attempt : {};
  const why = skipReasonText(text(attempt.reason));
  return { sent, question, attempt: sent ? null : `Not sent: ${why}.` };
}

export function askReporterRefusalText(error: unknown): string {
  const status = errorStatus(error);
  if (errorCode(error) === "analysis_not_found" || status === 404) return "Not sent: this analysis no longer exists. Reload the item.";
  if (status === 403) return "Not sent: you may not send questions for this item.";
  const message = error instanceof Error && error.message ? error.message : "the request failed";
  return `Not sent: ${message}.`;
}

export type McpRisk = "read" | "write" | "admin" | "unknown";
export const MCP_RISKS: { value: McpRisk; label: string }[] = [
  { value: "read", label: "Read" },
  { value: "write", label: "Write" },
  { value: "admin", label: "Admin" },
  { value: "unknown", label: "Not classified" },
];
// Mirrors tool_approval: write, admin and unknown capabilities of an unattended run need approval.
export const MCP_RISK_HINT = "Only Read tools run in chat and read-only runs. Every other class needs approval in unattended runs.";

export function normalizedRisk(value: unknown): McpRisk {
  const risk = text(value).toLowerCase();
  return risk === "read" || risk === "write" || risk === "admin" ? risk : "unknown";
}

export type McpToolBinding = { id: string; tool: string; enabled: boolean; risk: McpRisk; policy: Record<string, unknown> };

export function mcpToolBindings(bindings: unknown, serverName: string): McpToolBinding[] {
  const server = serverName.trim().toLowerCase();
  return (Array.isArray(bindings) ? bindings : [])
    .filter(isRecord)
    .filter((row) => row.capability_kind === "mcp_capability" && row.source_entity_type === "mcp_server_tool")
    .map((row) => {
      const config = isRecord(row.binding_config) ? row.binding_config : {};
      const policy = isRecord(row.policy_config) ? row.policy_config : {};
      return { row, config, policy };
    })
    .filter(({ config }) => text(config.serverName).toLowerCase() === server && text(config.toolName))
    .map(({ row, config, policy }) => ({
      id: text(row.id), tool: text(config.toolName), enabled: row.is_enabled === true, risk: normalizedRisk(policy.risk), policy,
    }))
    .sort((a, b) => a.tool.localeCompare(b.tool));
}

// The server replaces the whole policy, so the stored one is sent with only risk changed.
export function riskPatch(binding: Pick<McpToolBinding, "policy">, risk: McpRisk): { policy_config: Record<string, unknown> } {
  return { policy_config: { ...binding.policy, risk } };
}

export function riskSavedText(tool: string, risk: McpRisk): string {
  return `${tool} is now ${MCP_RISKS.find((option) => option.value === risk)?.label ?? risk}.`;
}

export const UNATTENDED_WARNING =
  "Tools listed here may write in runs no person started, without a per-call approval.";

// Same pattern as the backend's tool name check.
const TOOL_NAME = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/;

export function unattendedToolProblem(name: string, current: string[]): string | null {
  const value = name.trim();
  if (!value) return "Enter a tool name.";
  if (!TOOL_NAME.test(value)) return "Use letters, digits and _ . : - only.";
  if (current.includes(value)) return "This tool is already listed.";
  return null;
}
