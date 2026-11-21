// The secret_rebind_required refusal of a Workspace connection test or save: read, focus field and sentence.
import { isRecord } from "./workspaceConnectionTypes";

// The `secret_rebind_required` refusal of a Workspace connection test or save (409, backend R1). readJson
// throws it as SecretRebindRequiredError; it is read here by shape (`refusal` with field-name lists), so a
// refusal from any bundle or test realm is recognised. Nothing is retried: the stored secret is never sent to a
// changed address unless the author re-enters it.
export type ConnectionRebindRefusal = {
  changedTargetFields: string[];
  keptFields: string[];
};

const FIELD_NAME = /^[a-z][a-z0-9_]{0,63}$/;
const fieldNames = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter(
        (item): item is string =>
          typeof item === "string" && FIELD_NAME.test(item),
      )
    : [];

export function rebindRefusalOf(
  error: unknown,
): ConnectionRebindRefusal | null {
  if (!isRecord(error) || !isRecord(error.refusal)) return null;
  return {
    changedTargetFields: fieldNames(error.refusal.changedTargetFields),
    keptFields: fieldNames(error.refusal.keptFields),
  };
}

/** The field to focus: the chosen method's secret when the refusal keeps it, else the first kept secret. */
export function rebindFocusField(
  refusal: ConnectionRebindRefusal,
  chosenSecret: string | null,
): string | null {
  if (chosenSecret && refusal.keptFields.includes(chosenSecret))
    return chosenSecret;
  return refusal.keptFields[0] ?? chosenSecret;
}

// "Password" -> "password", "Personal access token" -> "personal access token", "API token" stays.
const inSentence = (label: string): string =>
  /^[A-Z][a-z]/.test(label)
    ? label.charAt(0).toLowerCase() + label.slice(1)
    : label;

export function rebindRefusalText(
  action: "test" | "save",
  label: string,
  secretLabel: string,
): string {
  const secret = inSentence(secretLabel);
  const verb = action === "test" ? "Not tested" : "Not saved";
  return `${verb}: the ${label} URL changed, so the stored ${secret} is not sent to the new address. Enter the ${secret} again for the new URL, then ${action} again.`;
}
