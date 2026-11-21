// The generic sign-in form of a named connection (delivery 3): the connector descriptor's fields, rendered by
// kind, for every connector type whose descriptor form is "fields" (Kubernetes, AWS, Git hosts, observability,
// clouds). Pure: no requests, no React. Secrets are write-only: a stored one is "stored", never filled in.

import type { NamedConnection, NamedDescriptor } from "./namedConnectionsTypes";

export type FieldsView = {
  errors: Record<string, { message: string; live: boolean }>;
  // A secret stored on the saved connection: leaving it empty keeps it.
  keepable: Record<string, boolean>;
};

const URL_PATTERN = /^https?:\/\/\S+$/i;

/** Which fields stop a save, and which stored secrets an empty input keeps. */
export function fieldsView(
  descriptor: NamedDescriptor,
  draft: Record<string, string>,
  connection: NamedConnection | null,
): FieldsView {
  const errors: FieldsView["errors"] = {};
  const keepable: Record<string, boolean> = {};
  for (const field of descriptor.fields) {
    const value = (draft[field.name] ?? "").trim();
    if (field.kind === "secret") {
      keepable[field.name] = connection?.secretStatus[field.name] === true;
      if (field.required && !value && !keepable[field.name])
        errors[field.name] = { message: `Enter ${field.label}.`, live: false };
      continue;
    }
    if (field.required && !value) errors[field.name] = { message: `Enter ${field.label}.`, live: false };
    else if (field.kind === "url" && value && !URL_PATTERN.test(value))
      errors[field.name] = { message: `${field.label}: an http(s) URL.`, live: true };
  }
  return { errors, keepable };
}

/** The save body's connection fields: every non-secret field the draft holds (empty clears it), typed secrets. */
export function fieldsSaveFields(descriptor: NamedDescriptor, draft: Record<string, string>): Record<string, string> {
  const body: Record<string, string> = {};
  for (const field of descriptor.fields) {
    if (!(field.name in draft)) continue;
    const value = draft[field.name] ?? "";
    if (field.kind === "secret") {
      if (value.trim()) body[field.name] = value.trim();
    } else {
      body[field.name] = value.trim();
    }
  }
  return body;
}
