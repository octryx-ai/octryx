// REST API model: the test call's parameters, request body and answer view.
import type { RestOperation, RestParameter, TestAnswer, TestSuccess } from "./restApisApi";
import { coerceValue, paramType } from "./restOperationEditorModel";

// ---- test call ---------------------------------------------------------------------------------------------------

/** The parameters a person would fill in: hidden or fixed ones are set by Octryx, not by the caller. */
export function testParameters(op: RestOperation): RestParameter[] {
  return op.parameters.filter((param) => {
    const overlay = op.params_overlay[param.name];
    return !(overlay?.hidden || (overlay?.value !== undefined && overlay.value !== ""));
  });
}

export type TestDraft = { workspaceId: string; mode: "form" | "json"; values: Record<string, string>; json: string };

export function testBody(op: RestOperation, draft: TestDraft): { body: Record<string, unknown> } | { error: string } {
  let args: Record<string, unknown> = {};
  if (draft.mode === "json") {
    try {
      const parsed: unknown = draft.json.trim() ? JSON.parse(draft.json) : {};
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return { error: "The arguments must be a JSON object." };
      args = parsed as Record<string, unknown>;
    } catch {
      return { error: "The arguments are not valid JSON." };
    }
  } else {
    for (const [name, raw] of Object.entries(draft.values)) {
      if (raw.trim() === "") continue;
      const type = paramType(op, name);
      // A list ($select's alias select) is typed as values separated by commas.
      args[name] = type === "array" ? raw.split(",").map((item) => item.trim()).filter(Boolean) : coerceValue(raw, type);
    }
  }
  return { body: { ...(draft.workspaceId ? { workspace_id: draft.workspaceId } : {}), arguments: args } };
}

export const TEST_CODE_WORDS: Record<string, string> = {
  not_granted: "Not granted to your roles",
  scope_violation: "Outside your data scope",
  // Audit rows recorded while writes were not offered.
  write_phase_2: "Write refused (writes were not offered yet)",
  capability_exceeded: "This run may not write here",
  invalid_arguments: "Arguments do not fit",
  no_connection: "No connection",
  auth_config: "Authentication incomplete",
  invalid_cursor: "Unknown cursor",
  scope_filter_unavailable: "Result filter could not check the answer",
  host_changed: "Would leave the connection's host",
  egress_refused: "Refused by the egress policy",
  request_failed: "Request failed",
  http_error: "The API answered with an error",
};

export const isTestSuccess = (answer: TestAnswer): answer is TestSuccess => !("error" in answer);

export type TestView = {
  ok: boolean;
  title: string;
  message: string | null;
  status: string;
  httpStatus: number | null;
  kept: number | null;
  dropped: number;
  scope: string;
  data: unknown;
  durationMs: number | null;
};

export function scopeText(scope: {
  params?: Record<string, unknown>;
  result_filter?: { field: string; value: unknown } | null;
  body?: Record<string, unknown>;
} | null | undefined): string {
  const params = Object.entries(scope?.params ?? {}).map(([name, value]) => `${name} = ${String(value)}`);
  const body = Object.entries(scope?.body ?? {}).map(([name, value]) => `body ${name} = ${String(value)}`);
  const filter = scope?.result_filter ? [`filter ${scope.result_filter.field} = ${String(scope.result_filter.value)}`] : [];
  return [...params, ...body, ...filter].join(" · ") || "No scope";
}

export function testView(answer: TestAnswer): TestView {
  if (isTestSuccess(answer)) {
    return {
      ok: true, title: "Call succeeded", message: null, status: "Succeeded", httpStatus: answer.status_code,
      kept: answer.record_count, dropped: answer.dropped_out_of_scope, scope: scopeText(answer.scope), data: answer.data,
      durationMs: answer.run?.duration_ms ?? null,
    };
  }
  const code = answer.code ?? "";
  return {
    ok: false,
    title: TEST_CODE_WORDS[code] ?? "Call refused",
    message: answer.error,
    status: answer.run?.status === "refused" ? "Refused" : "Failed",
    httpStatus: answer.run?.http_status ?? null,
    kept: null,
    dropped: answer.run?.dropped_out_of_scope ?? 0,
    scope: "",
    data: null,
    durationMs: answer.run?.duration_ms ?? null,
  };
}
