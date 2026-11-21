// Plugin settings form: fields from the plugin's schema, the draft, the PUT body with problems, and refusals in words.
import { isRecord } from "./pluginRecordGuard";

export type SettingsSchema = { type?: string; title?: string; properties?: Record<string, Record<string, unknown>>; required?: string[] };

export type SettingField = {
  key: string;
  label: string;
  description: string;
  control: "text" | "number" | "integer" | "boolean" | "enum" | "secret";
  options: string[];
  required: boolean;
  // Plain values as stored; a secret only says whether it is set.
  value: string | number | boolean | null;
  secretSet: boolean;
};

const words = (key: string) => {
  const spaced = key.replace(/[_-]+/g, " ").trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : key;
};

export function isSecretSpec(spec: Record<string, unknown>): boolean {
  return spec.format === "password" || spec["x-secret"] === true;
}

/** The form's fields from the plugin's schema and the stored values (GET /settings), in the schema's order. */
export function settingsFields(schema: SettingsSchema | null | undefined, values: Record<string, unknown> | null | undefined): SettingField[] {
  const properties = schema?.properties ?? {};
  const required = new Set(schema?.required ?? []);
  return Object.entries(properties).map(([key, raw]) => {
    const spec = isRecord(raw) ? raw : {};
    const stored = values?.[key];
    const options = Array.isArray(spec.enum) ? spec.enum.map((item) => String(item)) : [];
    const secret = isSecretSpec(spec);
    const control: SettingField["control"] = secret ? "secret"
      : options.length ? "enum"
        : spec.type === "boolean" ? "boolean"
          : spec.type === "integer" ? "integer"
            : spec.type === "number" ? "number" : "text";
    const fallback = spec.default;
    const value = secret ? null
      : stored !== undefined && stored !== null && !isRecord(stored) ? (stored as string | number | boolean)
        : fallback !== undefined && !isRecord(fallback) ? (fallback as string | number | boolean) : null;
    return {
      key,
      label: typeof spec.title === "string" && spec.title ? spec.title : words(key),
      description: typeof spec.description === "string" ? spec.description : "",
      control, options, required: required.has(key), value,
      secretSet: secret && isRecord(stored) && stored.set === true,
    };
  });
}

export type SettingsDraft = Record<string, string | boolean>;

export function settingsDraft(fields: SettingField[]): SettingsDraft {
  return Object.fromEntries(fields.map((field) => [field.key,
    field.control === "boolean" ? field.value === true : field.control === "secret" || field.value === null ? "" : String(field.value)]));
}

/**
 * The PUT body and what is wrong before sending: numbers parsed, an empty plain field cleared (null), an empty secret
 * left out (the stored one stays). A required plain field must have a value; a required secret must be set or typed.
 */
export function settingsPayload(fields: SettingField[], draft: SettingsDraft): { values: Record<string, unknown>; problems: Record<string, string> } {
  const values: Record<string, unknown> = {};
  const problems: Record<string, string> = {};
  for (const field of fields) {
    const raw = draft[field.key];
    if (field.control === "boolean") { values[field.key] = raw === true; continue; }
    const text = typeof raw === "string" ? raw.trim() : "";
    if (field.control === "secret") {
      if (text) values[field.key] = text;
      else if (field.required && !field.secretSet) problems[field.key] = "Required.";
      continue;
    }
    if (!text) {
      if (field.required) problems[field.key] = "Required.";
      else values[field.key] = null;
      continue;
    }
    if (field.control === "number" || field.control === "integer") {
      const number = Number(text);
      if (!Number.isFinite(number) || (field.control === "integer" && !Number.isInteger(number))) {
        problems[field.key] = field.control === "integer" ? "A whole number." : "A number.";
        continue;
      }
      values[field.key] = number;
      continue;
    }
    if (field.control === "enum" && !field.options.includes(text)) { problems[field.key] = "Choose one of the options."; continue; }
    values[field.key] = text;
  }
  return { values, problems };
}

const SETTINGS_WORDS: Record<string, string> = {
  plugin_setting_invalid: "A value does not fit the setting",
  plugin_setting_required: "A required setting is missing",
  plugin_setting_unknown: "The plugin does not know a setting",
};

/** A refused save in words (422 codes), followed by the server's sentence. */
export function settingsErrorText(error: unknown): string {
  const value = isRecord(error) ? error : {};
  const code = typeof value.code === "string" ? value.code : "";
  const message = error instanceof Error && error.message && error.message !== code ? error.message : "";
  const words = SETTINGS_WORDS[code];
  if (words) return message ? `${words}: ${message}` : `${words}.`;
  if (value.status === 403) return message || "Only who may install this plugin changes its settings.";
  return message || "The settings could not be saved.";
}
