// The explicit `secret_rebind_required` refusal: a tool-config save or test that changes a connection
// target while keeping a stored secret is answered with 409 and field names only. The admin either re-enters every
// kept secret or confirms, in a second explicit step, that the stored secret may be sent to the new target.
// Contract: backend/app/services/tool_config/secret_rebind.py (SecretRebindRequiredError.detail()).

export const SECRET_REBIND_REQUIRED = "secret_rebind_required";
export const CONFIRM_SECRET_REBIND_FIELD = "confirm_secret_rebind";

export type SecretRebindRefusal = {
  toolName: string;
  changedTargetFields: string[];
  keptFields: string[];
};

// A field or tool name: nothing else of the refusal is ever read, echoed or rendered.
const NAME_PATTERN = /^[a-z][a-z0-9_]{0,63}$/;

function names(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && NAME_PATTERN.test(item));
}

// The refusal carried by a response, or null for any other answer (including a 409 with another state).
export function parseSecretRebindRefusal(status: number, payload: unknown): SecretRebindRefusal | null {
  if (status !== 409 || !payload || typeof payload !== "object") return null;
  const detail = (payload as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object") return null;
  const record = detail as Record<string, unknown>;
  if (record.state !== SECRET_REBIND_REQUIRED) return null;
  const toolName = typeof record.tool_name === "string" && NAME_PATTERN.test(record.tool_name) ? record.tool_name : "";
  return {
    toolName,
    changedTargetFields: names(record.changed_target_fields),
    keptFields: names(record.kept_fields),
  };
}

export class SecretRebindRequiredError extends Error {
  readonly refusal: SecretRebindRefusal;

  constructor(refusal: SecretRebindRefusal) {
    super(secretRebindSummary(refusal));
    this.name = "SecretRebindRequiredError";
    this.refusal = refusal;
  }
}

// "confluence_password" -> "confluence password": the label the forms already show for a field.
export function fieldLabel(field: string): string {
  return field.replace(/_/g, " ");
}

function labelList(fields: string[]): string {
  return fields.map(fieldLabel).join(", ");
}

export function secretRebindSummary(refusal: SecretRebindRefusal): string {
  const changed = labelList(refusal.changedTargetFields) || "the connection target";
  const kept = labelList(refusal.keptFields) || "a stored secret";
  return `Not saved: ${changed} changed, and the stored ${kept} would be sent to the new target.`;
}

export function secretRebindConfirmText(refusal: SecretRebindRefusal): string {
  const kept = labelList(refusal.keptFields) || "stored secret";
  const changed = labelList(refusal.changedTargetFields) || "connection target";
  return `Send the stored ${kept} to the host now set in ${changed}? Confirm only if you trust that host; the confirmation is audited.`;
}

// Kept fields that still lack a new value; the re-enter path resubmits only when this is empty.
export function missingSecretReentries(refusal: SecretRebindRefusal, values: Record<string, unknown>): string[] {
  return refusal.keptFields.filter((field) => !String(values[field] ?? "").trim());
}

export function reentryErrorText(missing: string[]): string {
  return `Enter a new value for ${labelList(missing)} before saving.`;
}

// The confirm path: the same JSON body plus the explicit confirmation.
export function withSecretRebindConfirmation<T extends Record<string, unknown>>(body: T): T & { confirm_secret_rebind: true } {
  return { ...body, [CONFIRM_SECRET_REBIND_FIELD]: true } as T & { confirm_secret_rebind: true };
}

// The confirm path for a form post: the same fields plus confirm_secret_rebind=true (a copy; the input is kept).
export function formWithSecretRebindConfirmation(form: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(form);
  next.set(CONFIRM_SECRET_REBIND_FIELD, "true");
  return next;
}

// A first submission never carries a confirmation, whatever a previous confirm step sent.
export function formWithoutSecretRebindConfirmation(form: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(form);
  next.delete(CONFIRM_SECRET_REBIND_FIELD);
  return next;
}
