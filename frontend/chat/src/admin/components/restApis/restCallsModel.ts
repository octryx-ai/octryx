// REST API model: the calls audit list, what admitted a write and the calls filter.
import { approvalDetailHref } from "../../../chat/approval/approvalDetailModel";
import type { RefusedCallScope, RestCall } from "./restApisApi";
import type { OperationState } from "./restOperationsModel";
import { TEST_CODE_WORDS } from "./restTestCallModel";

// ---- calls (audit) -----------------------------------------------------------------------------------------------

export function callStatus(call: Pick<RestCall, "status" | "failure_category">): OperationState {
  if (call.status === "succeeded") return { label: "Succeeded", tone: "neutral" };
  if (call.status === "refused") return { label: "Refused", tone: "attention", hint: TEST_CODE_WORDS[call.failure_category] };
  if (call.status === "running") return { label: "Running", tone: "info" };
  return { label: "Failed", tone: "problem", hint: TEST_CODE_WORDS[call.failure_category] };
}

const valueText = (params: Record<string, unknown>) =>
  Object.entries(params).map(([name, value]) => `${name} = ${String(value)}`).join(", ");

/**
 * A scope refusal in words: what the call asked for and what the caller's grants allow, e.g.
 * "Asked for assignment_group = G2; allowed: admin → assignment_group = G1 (filter assignment_group = G1)".
 */
export function refusedScopeText(scope: RefusedCallScope): string {
  const asked = valueText(scope.requested ?? {}) || "no scoped value";
  const allowed = (scope.allowed ?? []).map((grant) => {
    const filter = grant.result_filter ? ` (filter ${grant.result_filter.field} = ${String(grant.result_filter.value)})` : "";
    return `${grant.role} → ${valueText(grant.params ?? {}) || "no fixed value"}${filter}`;
  });
  return `Asked for ${asked}; allowed: ${allowed.length ? allowed.join("; ") : "no scoped grant"}`;
}

export const isRefusedScope = (scope: RestCall["scope"]): scope is RefusedCallScope => scope?.refused === true;

/** "rest__demo__list_tickets" → "demo › list_tickets". */
export function operationOfTool(toolName: string): string {
  const match = /^rest__([a-z][a-z0-9_]*?)__(.+)$/.exec(toolName);
  return match ? `${match[1]} › ${match[2]}` : toolName;
}

export const durationText = (ms: number | null | undefined) =>
  ms === null || ms === undefined ? "—" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;

// ---- calls: what admitted a write (backend) ----------------------------------------------------------------

export type CallAdmission = { label: string; id: string; shortId: string; href: string | null; linkText: string };

/**
 * The approval or chat write plan that admitted a write. An approval opens its detail page (who asked, who decided,
 * the masked request; backend); a write plan is decided in its chat, so that link opens the chat. Without a
 * chat the plan's id is shown quietly.
 */
export function callAdmission(call: Pick<RestCall, "approval_id" | "write_plan_id" | "session_id">): CallAdmission | null {
  const href = call.session_id ? `/chat?session_id=${encodeURIComponent(call.session_id)}` : null;
  if (call.approval_id) {
    return { label: "Approval", id: call.approval_id, shortId: call.approval_id.slice(0, 8), href: approvalDetailHref(call.approval_id),
      linkText: "Approval ›" };
  }
  if (call.write_plan_id) {
    return { label: "Write plan", id: call.write_plan_id, shortId: call.write_plan_id.slice(0, 8), href, linkText: "Write plan ›" };
  }
  return null;
}

const WRITE_REFUSALS = new Set(["capability_exceeded", "write_phase_2"]);

/** A write call: the server says so (`write`), or something admitted it, or it was refused as a write. */
export const isWriteCall = (call: Pick<RestCall, "write" | "approval_id" | "write_plan_id" | "failure_category">) =>
  call.write ?? Boolean(call.approval_id || call.write_plan_id || WRITE_REFUSALS.has(call.failure_category));

export const filterCalls = <T extends Pick<RestCall, "write" | "approval_id" | "write_plan_id" | "failure_category">>(
  calls: T[], writesOnly: boolean,
) => (writesOnly ? calls.filter(isWriteCall) : calls);

// ---- calls filter (backend) --------------------------------------------------------------------------------

export type CallsFilter = { definitionId: string; opId: string; writesOnly: boolean };

/** The calls query: the server filters by API and operation; an operation only counts within its API. */
export function callsQuery(filter: Pick<CallsFilter, "definitionId" | "opId">, limit = 200): string {
  const query = new URLSearchParams({ limit: String(limit) });
  if (filter.definitionId) {
    query.set("definition_id", filter.definitionId);
    if (filter.opId) query.set("op_id", filter.opId);
  }
  return query.toString();
}

/** The filter a link opened with (`?rest_api=<id>&rest_op=<id>`), so an API's detail can link to its calls. */
export function callsFilterFromSearch(search: string): Pick<CallsFilter, "definitionId" | "opId"> {
  const params = new URLSearchParams(search);
  return { definitionId: params.get("rest_api") ?? "", opId: params.get("rest_api") ? params.get("rest_op") ?? "" : "" };
}

/** The Calls page opened on one API (and operation). */
export const callsHref = (definitionId: string, opId = "") =>
  `/chat?area=admin&tab=restApiCalls&rest_api=${encodeURIComponent(definitionId)}${opId ? `&rest_op=${encodeURIComponent(opId)}` : ""}`;
