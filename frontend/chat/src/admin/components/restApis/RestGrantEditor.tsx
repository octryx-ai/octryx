import { useEffect, useId, useState } from "react";

import { loadRoleOptions, type RestOperation } from "./restApisApi";
import { OFFERED_TO_NOBODY } from "./restOperationsModel";
import { bodyFieldPaths, grantDraft, grantProblems, grantWarning, hasRequestBody, isReadDraft, unsavedHint, type GrantDraft, type OperationDraft } from "./restOperationEditorModel";
import { Field, FormError, Warnings } from "./restApisParts";
import type { Workspace } from "./RestApisPage";

type RoleOptions = { platform: string[]; work: Array<{ key: string; name: string }> };

// Who may call one operation, limited to which data. The API is called with one technical account, so these grants
// are the whole authorization: a role (platform role or work-role key), optionally one Workspace, and a data scope of
// fixed parameter values plus an optional result filter, and for an operation with a JSON body fixed body fields
// (backend: set last, a body naming another value there is refused).
// A grant's scope hint shows only while that grant has unsaved edits, marked as such; once saved, the server's warning
// for the operation says it (backend).
export function RestGrantEditor({ operation, draft, saved, onChange, workspaces, error }: {
  operation: RestOperation;
  draft: OperationDraft;
  saved: GrantDraft[];
  onChange: (draft: OperationDraft) => void;
  workspaces: Workspace[];
  error: string | null;
}) {
  const listId = useId();
  const bodyListId = useId();
  const [roles, setRoles] = useState<RoleOptions>({ platform: [], work: [] });
  useEffect(() => {
    let live = true;
    void loadRoleOptions().then((options) => { if (live) setRoles(options); });
    return () => { live = false; };
  }, []);

  const grants = draft.grants;
  const setGrants = (next: GrantDraft[]) => onChange({ ...draft, grants: next });
  const put = (index: number, patch: Partial<GrantDraft>) => setGrants(grants.map((grant, at) => (at === index ? { ...grant, ...patch } : grant)));
  const params = operation.parameters.map((param) => param.name);
  const read = isReadDraft(operation, draft);
  const withBody = hasRequestBody(operation);
  const bodyPaths = withBody ? bodyFieldPaths(operation) : [];

  return (
    <div className="rst-stack" data-testid="rest-grants">
      <p className="rst-text">
        The API is called with the connection's technical account. Only the roles below may call this operation, and only
        within their data scope.
      </p>
      {!grants.length ? <p className="rst-muted" data-testid="rest-grants-none">{OFFERED_TO_NOBODY}</p> : null}
      {bodyPaths.length ? (
        <datalist id={bodyListId}>
          {bodyPaths.map((field) => <option key={field.path} value={field.path}>{field.type}</option>)}
        </datalist>
      ) : null}
      <datalist id={listId}>
        {roles.platform.map((name) => <option key={`p-${name}`} value={name}>Platform role</option>)}
        {roles.work.map((role) => <option key={`w-${role.key}`} value={role.key}>{`Work role: ${role.name}`}</option>)}
      </datalist>
      {grants.map((grant, index) => (
        <GrantCard key={index} grant={grant} index={index} saved={saved[index]} params={params} read={read} withBody={withBody}
          listId={listId} bodyListId={bodyPaths.length ? bodyListId : undefined} workspaces={workspaces}
          onPut={(patch) => put(index, patch)} onRemove={() => setGrants(grants.filter((_, at) => at !== index))} />
      ))}
      <FormError text={error} />
      <button type="button" className="ds-btn rst-back" onClick={() => setGrants([...grants, grantDraft()])} data-testid="rest-grant-add">
        Add grant
      </button>
    </div>
  );
}

type GrantCardProps = {
  grant: GrantDraft;
  index: number;
  saved: GrantDraft | undefined;
  params: string[];
  read: boolean;
  withBody: boolean;
  listId: string;
  bodyListId: string | undefined;
  workspaces: Workspace[];
  onPut: (patch: Partial<GrantDraft>) => void;
  onRemove: () => void;
};

function GrantCard({ grant, index, saved, params, read, withBody, listId, bodyListId, workspaces, onPut, onRemove }: GrantCardProps) {
  const problems = grantProblems(grant);
  const edited = JSON.stringify(grant) !== JSON.stringify(saved);
  const hint = edited ? grantWarning(grant, !read, withBody) : null;
  const warning = hint ? unsavedHint(hint) : null;
  const unused = params.filter((name) => !grant.scope.some((row) => row.param === name));
  return (
    <section className="rst-card" data-testid={`rest-grant-${index}`}>
      <div className="rst-card__head">
        <h3 className="rst-card__title">{grant.role || "New grant"}</h3>
        <button type="button" className="ds-btn ds-btn--sm ds-btn--ghost" onClick={onRemove}>
          Remove grant
        </button>
      </div>
      <div className="rst-grid">
        <Field label="Role" hint="A platform role or a work-role key." error={problems.role}>
          <input className="admin-panel__input" list={listId} value={grant.role} onChange={(event) => onPut({ role: event.target.value })}
            placeholder="service_desk" data-testid={`rest-grant-${index}-role`} />
        </Field>
        <Field label="Workspace">
          <select className="admin-panel__input" value={grant.workspaceId} onChange={(event) => onPut({ workspaceId: event.target.value })}>
            <option value="">Any Workspace</option>
            {workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}
          </select>
        </Field>
      </div>
      <DataScope grant={grant} index={index} unused={unused} error={problems.scope} onPut={onPut} />
      {withBody ? (
        <BodyScope grant={grant} index={index} listId={bodyListId} error={problems.bodyScope}
          onChange={(bodyScope) => onPut({ bodyScope })} />
      ) : null}
      <div className="rst-grid">
        <Field label="Result filter: field (optional)" hint="Records where this field differs are dropped and counted.">
          <input className="admin-panel__input" value={grant.filterField} onChange={(event) => onPut({ filterField: event.target.value })} placeholder="e.g. group.id"
            data-testid={`rest-grant-${index}-filter-field`} />
        </Field>
        <Field label="must equal" error={problems.filter}>
          <input className="admin-panel__input" value={grant.filterValue} onChange={(event) => onPut({ filterValue: event.target.value })}
            data-testid={`rest-grant-${index}-filter-value`} />
        </Field>
      </div>
      {warning ? <Warnings items={[warning]} testId={`rest-grant-${index}-warning`} /> : null}
    </section>
  );
}

function DataScope({ grant, index, unused, error, onPut }: {
  grant: GrantDraft;
  index: number;
  unused: string[];
  error?: string;
  onPut: (patch: Partial<GrantDraft>) => void;
}) {
  return (
    <>
      <h4 className="rst-subhead">Data scope</h4>
      {grant.scope.length ? null : <p className="rst-muted">No fixed values: this role may call it with any parameters.</p>}
      {grant.scope.map((row, rowIndex) => (
        <div key={rowIndex} className="rst-scope-line">
          <Field label="Parameter">
            <select className="admin-panel__input" value={row.param} onChange={(event) => onPut({ scope: grant.scope.map((item, at) => (at === rowIndex ? { ...item, param: event.target.value } : item)) })}
              data-testid={`rest-grant-${index}-scope-${rowIndex}-param`}>
              <option value="">Choose…</option>
              {[row.param, ...unused].filter(Boolean).map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </Field>
          <Field label="Fixed to">
            <input className="admin-panel__input" value={row.value} onChange={(event) => onPut({ scope: grant.scope.map((item, at) => (at === rowIndex ? { ...item, value: event.target.value } : item)) })}
              data-testid={`rest-grant-${index}-scope-${rowIndex}-value`} />
          </Field>
          <button type="button" className="ds-btn ds-btn--ghost" onClick={() => onPut({ scope: grant.scope.filter((_, at) => at !== rowIndex) })}
            aria-label={`Remove ${row.param || "scope line"}`}>Remove</button>
        </div>
      ))}
      {error ? <small className="rst-field__error" role="alert">{error}</small> : null}
      {unused.length ? (
        <button type="button" className="ds-btn ds-btn--sm rst-back" onClick={() => onPut({ scope: [...grant.scope, { param: unused[0], value: "" }] })}
          data-testid={`rest-grant-${index}-add-scope`}>
          Add a fixed value
        </button>
      ) : null}
    </>
  );
}

// Fixed body fields of one grant: a dotted path in the JSON body and the value Octryx sets there, after the model's
// own body. A call whose body names another value at that path is refused, never rewritten.
function BodyScope({ grant, index, listId, error, onChange }: {
  grant: GrantDraft;
  index: number;
  listId?: string;
  error?: string;
  onChange: (rows: GrantDraft["bodyScope"]) => void;
}) {
  const rows = grant.bodyScope;
  const putRow = (at: number, patch: Partial<GrantDraft["bodyScope"][number]>) =>
    onChange(rows.map((row, position) => (position === at ? { ...row, ...patch } : row)));
  return (
    <div className="rst-stack" data-testid={`rest-grant-${index}-body-scope`}>
      <h4 className="rst-subhead">Body scope</h4>
      {rows.length ? null : <p className="rst-muted">No fixed body fields: this role may send any body.</p>}
      {rows.map((row, rowIndex) => (
        <div key={rowIndex} className="rst-scope-line">
          <Field label="Body field">
            <input className="admin-panel__input" list={listId} value={row.param} placeholder="assignment_group"
              onChange={(event) => putRow(rowIndex, { param: event.target.value })} data-testid={`rest-grant-${index}-body-${rowIndex}-path`} />
          </Field>
          <Field label="Fixed to">
            <input className="admin-panel__input" value={row.value} onChange={(event) => putRow(rowIndex, { value: event.target.value })}
              data-testid={`rest-grant-${index}-body-${rowIndex}-value`} />
          </Field>
          <button type="button" className="ds-btn ds-btn--ghost" onClick={() => onChange(rows.filter((_, at) => at !== rowIndex))}
            aria-label={`Remove ${row.param || "body line"}`}>Remove</button>
        </div>
      ))}
      {error ? <small className="rst-field__error" role="alert">{error}</small> : null}
      <button type="button" className="ds-btn ds-btn--sm rst-back" onClick={() => onChange([...rows, { param: "", value: "" }])}
        data-testid={`rest-grant-${index}-add-body`}>
        Add a fixed body field
      </button>
    </div>
  );
}
