import { useState } from "react";

import { EmptyLine } from "../../../layout/EmptyLine";
import { FormSection } from "../../../layout/FormSection";
import { SidePanel } from "../../../layout/SidePanel";
import { AccessFields, AvailableInEditor, Field, type FieldErrors } from "./ConnectionFields";
import { accessBodyOf, missingAccess, type AccessValue } from "./connectionDraft";
import { createConnection } from "./connectionsApi";
import { fieldOptions, findType, type ConnectionType } from "./connectionTypes";
import type { AvailableIn, ConnectionDetail, WorkspaceRef } from "./connectionsModel";
import { accessFieldText, visibleAccessFields } from "./authFields";

// "Add connection": type, name, access and where it is available. The types and their access fields come
// from the server's descriptors (GET /api/v1/admin/connection-types). A second account of the same system is a
// second connection of that type. Uses (Knowledge, Tickets, Agent tools) are switched on in the connection itself.

const EMPTY_ACCESS: AccessValue = { values: {}, secrets: {} };

/** A new type's starting values: each select field preset to its first choice (the sign-in field: first auth kind). */
// An optional choice whose empty value is the server's default (OpenID Connect client authentication: the secret in
// the request body) starts empty, so it is only sent when chosen and never for another sign-in.
const EMPTY_IS_DEFAULT = /_client_auth$/;

function startingAccess(descriptor: ConnectionType | null): AccessValue {
  const values: Record<string, string> = {};
  for (const field of descriptor?.accessFields ?? []) {
    if (field.kind === "select" && !EMPTY_IS_DEFAULT.test(field.key)) {
      const first = fieldOptions(field, descriptor)[0];
      if (first) values[field.key] = first;
    }
  }
  return { values, secrets: {} };
}

export function AddConnectionPanel({ types, workspaces, onClose, onCreated }: {
  types: ConnectionType[]; workspaces: WorkspaceRef[]; onClose: () => void; onCreated: (detail: ConnectionDetail | null) => void;
}) {
  const [type, setType] = useState("");
  const [name, setName] = useState("");
  const [access, setAccess] = useState<AccessValue>(EMPTY_ACCESS);
  const [available, setAvailable] = useState<{ availableIn: AvailableIn; workspaceIds: string[] }>({ availableIn: "selected", workspaceIds: [] });
  const [errors, setErrors] = useState<FieldErrors>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const descriptor = findType(types, type);
  const shown = descriptor ? visibleAccessFields(descriptor.type, descriptor.accessFields, access.values) : [];
  const required = descriptor ? missingAccess(shown, access) : [];
  const missing = !types.length ? "The kinds of connection could not be loaded."
    : !type ? "Choose a type." : !name.trim() ? "Give it a name."
      // The labels as the form shows them, in their own case ("Bitbucket URL", not "bitbucket url").
      : required.length ? `Fill in ${required.map((field) => accessFieldText(type, field, access.values).label).join(", ")}.` : "";

  const chooseType = (next: string) => {
    // The name proposal is the type's own label ("Bitbucket"); a name the admin typed is kept.
    const proposed = findType(types, type)?.label ?? "";
    if (!name.trim() || name === proposed) setName(findType(types, next)?.label ?? "");
    setType(next);
    setAccess(next ? startingAccess(findType(types, next)) : EMPTY_ACCESS);
    setErrors(null);
  };

  const submit = async () => {
    if (missing) return;
    setBusy(true);
    setErrors(null);
    const result = await createConnection({
      type, name: name.trim(),
      access: accessBodyOf(shown, access),
      available_in: available.availableIn, workspaces: available.availableIn === "all" ? [] : available.workspaceIds,
    });
    setBusy(false);
    if (!result.ok) {
      setErrors({ field: result.field, message: result.message });
      setNotice(result.field ? "" : result.message);
      return;
    }
    onCreated(result.detail);
  };

  return (
    <SidePanel title="Add connection" onClose={onClose} testId="connection-add-panel"
      footer={(
        <>
          {notice || missing ? <span role="status" className="connections__notice" data-testid="connection-add-hint">{notice || missing}</span> : null}
          <button type="button" className="admin-panel__action-btn" onClick={onClose} data-testid="connection-add-cancel">Cancel</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={Boolean(missing) || busy}
            onClick={() => void submit()} data-testid="connection-add-submit">Add connection</button>
        </>
      )}
    >
      {types.length === 0 ? (
        <EmptyLine text="The kinds of connection could not be loaded." testId="connection-add-no-types" />
      ) : (
        <>
          <FormSection title="Connection">
            <Field label="Type" path="type" errors={errors}>
              <select className="admin-panel__input" value={type} onChange={(event) => chooseType(event.target.value)} data-testid="connection-add-type">
                <option value="">Choose…</option>
                {types.map((entry) => <option key={entry.type} value={entry.type}>{entry.label}</option>)}
              </select>
            </Field>
            <Field label="Name" path="name" errors={errors}>
              <input className="admin-panel__input" value={name} placeholder="e.g. Jira Cloud (team)" onChange={(event) => setName(event.target.value)}
                data-testid="connection-add-name" />
            </Field>
          </FormSection>
          {descriptor ? (
            <FormSection title="Access">
              <AccessFields fields={descriptor.accessFields} descriptor={descriptor} value={access} onChange={setAccess}
                stored={{}} readOnly={false} errors={errors} />
            </FormSection>
          ) : null}
          <FormSection title="Available in">
            <AvailableInEditor {...available} workspaces={workspaces} readOnly={false} errors={errors} onChange={setAvailable} />
          </FormSection>
        </>
      )}
    </SidePanel>
  );
}
