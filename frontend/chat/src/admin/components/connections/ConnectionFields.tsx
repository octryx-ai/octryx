import type { ReactNode } from "react";

import type { AccessValue } from "./connectionDraft";
import { accessFieldOptions, accessFieldText, accessOptionLabel, lowerFirst, visibleAccessFields, withAccessValue } from "./authFields";
import { authLabel, fieldOptions, type AccessField, type ConnectionType } from "./connectionTypes";
import type { AvailableIn, WorkspaceRef } from "./connectionsModel";

export type FieldErrors = { field: string; message: string } | null;

export function Field({ label, path, errors, children }: { label: string; path: string; errors: FieldErrors; children: ReactNode }) {
  const error = errors && errors.field === path ? errors.message : "";
  return (
    <label className="admin-panel__field connections__field" data-field={path}>
      <span>{label}</span>
      {children}
      {error ? <span className="connections__field-error" role="alert" data-testid={`field-error-${path}`}>{error}</span> : null}
    </label>
  );
}

const PLACEHOLDERS: Record<string, string> = { url: "e.g. https://acme.atlassian.net", email: "e.g. bot@example.com", list: "e.g. one, two" };

export function AccessFields({ fields, descriptor, value, onChange, stored, readOnly, errors }: {
  fields: AccessField[]; descriptor: ConnectionType | null; value: AccessValue; onChange: (next: AccessValue) => void;
  stored: Record<string, boolean>; readOnly: boolean; errors: FieldErrors;
}) {
  const label = (field: AccessField, text: string) => (field.required && !readOnly ? `${text} (required)` : text);
  const type = descriptor?.type ?? "";
  const setValue = (key: string, text: string) => onChange({ ...value, values: withAccessValue(type, value.values, key, text) });
  return (
    <>
      {visibleAccessFields(type, fields, value.values).map((shownField) => accessFieldText(type, shownField, value.values)).map((field) => {
        const path = `access.${field.key}`;
        if (field.secret) {
          const set = stored[field.key] === true;
          if (readOnly) return <p key={field.key} className="connections__fact" data-testid={`connection-stored-${field.key}`}>{field.label}: {set ? "set" : "not set"}</p>;
          return (
            // A stored secret is kept when the field stays empty, so replacing it is never required.
            <Field key={field.key} label={set ? `Replace ${lowerFirst(field.label)}` : label(field, field.label)} path={path} errors={errors}>
              <input className="admin-panel__input" type="password" autoComplete="new-password" value={value.secrets[field.key] ?? ""}
                placeholder={set ? "Stored · leave empty to keep it" : "Not set yet"}
                onChange={(event) => onChange({ ...value, secrets: { ...value.secrets, [field.key]: event.target.value } })}
                data-testid={`connection-secret-${field.key}`} />
            </Field>
          );
        }
        if (field.kind === "bool") {
          return (
            <label key={field.key} className="admin-panel__checkbox connections__check" data-field={path}>
              <input type="checkbox" checked={value.values[field.key] === "true"} disabled={readOnly}
                onChange={(event) => setValue(field.key, event.target.checked ? "true" : "false")} data-testid={`connection-access-${field.key}`} />
              <span>{field.label}</span>
            </label>
          );
        }
        if (field.kind === "select") {
          const current = value.values[field.key] ?? "";
          const choices = accessFieldOptions(type, field, value.values, fieldOptions(field, descriptor));
          const options = Array.from(new Set([...(current ? [current] : []), ...choices]));
          return (
            <Field key={field.key} label={label(field, field.label)} path={path} errors={errors}>
              <select className="admin-panel__input" value={current} disabled={readOnly} data-testid={`connection-access-${field.key}`}
                onChange={(event) => setValue(field.key, event.target.value)}>
                {current ? null : <option value="">Choose…</option>}
                {options.map((option) => <option key={option} value={option}>{accessOptionLabel(type, field.key, option) ?? authLabel(option)}</option>)}
              </select>
            </Field>
          );
        }
        return (
          <Field key={field.key} label={label(field, field.label)} path={path} errors={errors}>
            <input className="admin-panel__input" value={value.values[field.key] ?? ""} disabled={readOnly}
              type={field.kind === "url" ? "url" : field.kind === "email" ? "email" : "text"}
              inputMode={field.kind === "int" ? "numeric" : undefined} placeholder={field.placeholder || (PLACEHOLDERS[field.kind] ?? "")}
              onChange={(event) => setValue(field.key, event.target.value)} data-testid={`connection-access-${field.key}`} />
          </Field>
        );
      })}
    </>
  );
}

export function AvailableInEditor({ availableIn, workspaceIds, workspaces, readOnly, errors, onChange }: {
  availableIn: AvailableIn; workspaceIds: string[]; workspaces: WorkspaceRef[]; readOnly: boolean; errors: FieldErrors;
  onChange: (next: { availableIn: AvailableIn; workspaceIds: string[] }) => void;
}) {
  const toggle = (id: string) => onChange({ availableIn,
    workspaceIds: workspaceIds.includes(id) ? workspaceIds.filter((entry) => entry !== id) : [...workspaceIds, id] });
  return (
    <div className="connections__available" data-testid="connection-available-in">
      <div role="radiogroup" aria-label="Available in" className="connections__radios">
        {(["all", "selected"] as AvailableIn[]).map((option) => (
          <label key={option} className="admin-panel__checkbox connections__radio">
            <input type="radio" name="available-in" value={option} checked={availableIn === option} disabled={readOnly}
              onChange={() => onChange({ availableIn: option, workspaceIds })} />
            <span>{option === "all" ? "All workspaces" : "Selected workspaces"}</span>
          </label>
        ))}
      </div>
      {availableIn === "selected" ? (
        <fieldset className="connections__workspaces" aria-label="Workspaces" disabled={readOnly}>
          {workspaces.length === 0 ? <p className="connections__fact">No workspace yet.</p> : workspaces.map((ref) => (
            <label key={ref.id} className="admin-panel__checkbox connections__check">
              <input type="checkbox" checked={workspaceIds.includes(ref.id)} onChange={() => toggle(ref.id)}
                data-testid={`connection-workspace-${ref.id}`} />
              <span>{ref.name}</span>
            </label>
          ))}
        </fieldset>
      ) : null}
      {errors && errors.field === "workspaces" ? (
        <span className="connections__field-error" role="alert" data-testid="field-error-workspaces">{errors.message}</span>
      ) : null}
    </div>
  );
}
