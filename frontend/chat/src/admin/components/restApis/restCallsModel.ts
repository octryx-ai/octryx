import { approvalDetailHref } from "../../../chat/approval/approvalDetailModel";
import type { RefusedCallScope, RestCall } from "./restApisApi";
import type { OperationState } from "./restOperationsModel";
import { TEST_CODE_WORDS } from "./restTestCallModel";

export function callStatus(call: Pick<RestCall, "status" | "failure_category">): OperationState {
  if (call.status === "succeeded") return { label: "Succeeded", tone: "neutral" };
  if (call.status === "refused") return { label: "Refused", tone: "attention", hint: TEST_CODE_WORDS[call.failure_category] };
  if (call.status === "running") return { label: "Running", tone: "info" };
  return { label: "Failed", tone: "problem", hint: TEST_CODE_WORDS[call.failure_category] };
}

const valueText = (params: Record<string, unknown>) =>
  Object.entries(params).map(([name, value]) => `${name} = ${String(value)}`).join(", ");

export function refusedScopeText(scope: RefusedCallScope): string {
  const asked = valueText(scope.requested ?? {}) || "no scoped value";
  const allowed = (scope.allowed ?? []).map((grant) => {
    const filter = grant.result_filter ? ` (filter ${grant.result_filter.field} = ${String(grant.result_filter.value)})` : "";
    return `${grant.role} → ${valueText(grant.params ?? {}) || "no fixed value"}${filter}`;
  });
  return `Asked for ${asked}; allowed: ${allowed.length ? allowed.join("; ") : "no scoped grant"}`;
}

export const isRefusedScope = (scope: RestCall["scope"]): scope is RefusedCallScope => scope?.refused === true;

export function operationOfTool(toolName: string): string {
  const match = /^rest__([a-z][a-z0-9_]*?)__(.+)$/.exec(toolName);
  return match ? `${match[1]} › ${match[2]}` : toolName;
}

export const durationText = (ms: number | null | undefined) =>
  ms === null || ms === undefined ? "—" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;

export type CallAdmission = { label: string; id: string; shortId: string; href: string | null; linkText: string };

// A write plan is decided in its chat, so its link opens the chat.
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

export const isWriteCall = (call: Pick<RestCall, "write" | "approval_id" | "write_plan_id" | "failure_category">) =>
  call.write ?? Boolean(call.approval_id || call.write_plan_id || WRITE_REFUSALS.has(call.failure_category));

export const filterCalls = <T extends Pick<RestCall, "write" | "approval_id" | "write_plan_id" | "failure_category">>(
  calls: T[], writesOnly: boolean,
) => (writesOnly ? calls.filter(isWriteCall) : calls);

export type CallsFilter = { definitionId: string; opId: string; writesOnly: boolean };

export function callsQuery(filter: Pick<CallsFilter, "definitionId" | "opId">, limit = 200): string {
  const query = new URLSearchParams({ limit: String(limit) });
  if (filter.definitionId) {
    query.set("definition_id", filter.definitionId);
    if (filter.opId) query.set("op_id", filter.opId);
  }
  return query.toString();
}

export function callsFilterFromSearch(search: string): Pick<CallsFilter, "definitionId" | "opId"> {
  const params = new URLSearchParams(search);
  return { definitionId: params.get("rest_api") ?? "", opId: params.get("rest_api") ? params.get("rest_op") ?? "" : "" };
}

export const callsHref = (definitionId: string, opId = "") =>
  `/chat?area=admin&tab=restApiCalls&rest_api=${encodeURIComponent(definitionId)}${opId ? `&rest_op=${encodeURIComponent(opId)}` : ""}`;
