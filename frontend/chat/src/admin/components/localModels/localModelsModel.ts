// Local model licences (backend): the platform switch `local_models.permissive_only` and the
// licence of a model in the launcher's local model catalog (`{id, url, note, commercial_restriction, permissive}`).
//   GET|PUT /api/v1/admin/local-models -> {permissive_only, can_edit}; PUT {permissive_only} (platform admins, audited).

export const LOCAL_MODELS_PATH = "/api/v1/admin/local-models";
export const LOCAL_MODELS_AUDIT_ACTION = "admin.local_models.permissive_only_updated";

export type LocalModelsSetting = { permissiveOnly: boolean; canEdit: boolean };

const isRecord = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);

/** The server's answer; the switch is on unless the server says `false` (its default is on). */
export function readLocalModelsSetting(raw: unknown): LocalModelsSetting | null {
  if (!isRecord(raw) || !("permissive_only" in raw)) return null;
  return { permissiveOnly: raw.permissive_only !== false, canEdit: raw.can_edit === true };
}

export const localModelsBody = (permissiveOnly: boolean) => ({ permissive_only: permissiveOnly });

/** What the card shows: hidden when the GET is forbidden, read-only for everyone but platform admins. */
export function loadOutcome(status: number | null): "hidden" | "problem" {
  return status === 403 ? "hidden" : "problem";
}

const CODE_TEXT: Record<string, string> = {
  unknown_setting: "the server does not know this setting.",
  invalid_flag: "the value must be on or off.",
};

export function localModelsSaveError(status: number, body: unknown): string {
  if (status === 403) return "Not saved: only platform admins can change this switch.";
  if (status === 422) {
    const detail = isRecord(body) ? body.detail : null;
    const errors = isRecord(detail) && Array.isArray(detail.errors) ? detail.errors.filter(isRecord) : [];
    const code = errors.length ? String(errors[0].code ?? "") : "";
    return `Not saved: ${CODE_TEXT[code] ?? "this value was refused."}`;
  }
  return "Not saved: the request failed.";
}

export type LicenceTag = {
  label: string;
  url: string | null;
  /** Tooltip / short line: the restriction first, else the note. */
  detail: string;
  restricted: boolean;
};

/** A catalog model's licence as a quiet tag; a missing or unreadable licence counts as restricted ("Licence unknown"). */
export function licenceTag(raw: unknown): LicenceTag {
  if (!isRecord(raw) || typeof raw.id !== "string" || !raw.id.trim()) {
    return { label: "Licence unknown", url: null, detail: "No licence is recorded for this model.", restricted: true };
  }
  const url = typeof raw.url === "string" && /^https?:\/\//.test(raw.url) ? raw.url : null;
  const note = typeof raw.note === "string" ? raw.note.trim() : "";
  const restriction = typeof raw.commercial_restriction === "string" ? raw.commercial_restriction.trim() : "";
  const restricted = raw.permissive !== true;
  const detail = restriction ? `Commercial use only with ${restriction}.${note ? ` ${note}` : ""}` : note;
  return { label: raw.id.trim(), url, detail, restricted };
}
