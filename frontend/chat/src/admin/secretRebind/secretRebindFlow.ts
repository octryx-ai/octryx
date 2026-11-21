import { missingSecretReentries, reentryErrorText } from "./secretRebindModel";
import type { SecretRebindRefusal } from "./secretRebindModel";

// The explicit states after a `secret_rebind_required` refusal, shared by the admin connector panel and the
// /admin/tools form. `body` is the refused submission, resent unchanged (plus the confirmation) by the confirm step.
//   choose  -> the refusal is shown with its two options
//   reenter -> the kept secret fields need a new value; a save without them is stopped here, not sent
//   confirm -> the second, explicit click that sends the stored secret to the new target
export type SecretRebindStep = "choose" | "reenter" | "confirm";

export type SecretRebindFlow<B> = {
  refusal: SecretRebindRefusal;
  body: B;
  step: SecretRebindStep;
  missing: string[];
  error: string | null;
};

export function refusedFlow<B>(refusal: SecretRebindRefusal, body: B): SecretRebindFlow<B> {
  return { refusal, body, step: "choose", missing: [], error: null };
}

export function flowAtStep<B>(flow: SecretRebindFlow<B>, step: SecretRebindStep): SecretRebindFlow<B> {
  return { ...flow, step, missing: [], error: null };
}

// In the re-enter step: the flow with the missing fields named (nothing is sent), or null when every kept secret
// has a new value and the ordinary save may go ahead. Outside the re-enter step nothing is checked.
export function blockedReentry<B>(
  flow: SecretRebindFlow<B> | null,
  values: Record<string, unknown>,
): SecretRebindFlow<B> | null {
  if (!flow || flow.step !== "reenter") return null;
  const missing = missingSecretReentries(flow.refusal, values);
  return missing.length ? { ...flow, missing, error: reentryErrorText(missing) } : null;
}

// What the refusal says about one form field, shown next to that field.
export type RebindFieldRole = "changed_target" | "kept_secret" | "missing_secret";

export function rebindFieldRole<B>(flow: SecretRebindFlow<B> | null, field: string): RebindFieldRole | null {
  if (!flow) return null;
  if (flow.missing.includes(field)) return "missing_secret";
  if (flow.refusal.keptFields.includes(field)) return "kept_secret";
  if (flow.refusal.changedTargetFields.includes(field)) return "changed_target";
  return null;
}

export function rebindFieldHint(role: RebindFieldRole, step: SecretRebindStep): string {
  if (role === "changed_target") return "Target changed: the stored secret is not sent here without re-entry or confirmation.";
  if (role === "missing_secret") return "Required for the new target: enter a new value.";
  return step === "reenter" ? "Enter a new value for the new target." : "Stored secret kept from the previous target.";
}

// The input's extra class: attention for a changed target or kept secret, error for a missing re-entry.
export function rebindFieldClass<B>(flow: SecretRebindFlow<B> | null, field: string): string {
  const role = rebindFieldRole(flow, field);
  if (!role) return "";
  return role === "missing_secret" ? " security-field--error" : " security-field--attention";
}
