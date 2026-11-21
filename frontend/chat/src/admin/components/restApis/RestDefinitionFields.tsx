import type { AuthScheme } from "./restApisApi";
import { AUTH_SCHEMES, definitionAuthFields } from "./restAuthModel";
import { CSRF_FETCH_PATH_HINT, CSRF_HEADER, CSRF_HEADER_HINT, CSRF_HINT, CSRF_LABEL, csrfApplies, serverRowOfIndex, withScheme } from "./restOdataModel";
import { fieldError, type RestErrorView } from "./restErrorsModel";
import { type DefinitionEditDraft } from "./restDefinitionDraftsModel";
import { Field } from "./restApisParts";

type Context = {
  // Whether the API has write operations (null: not known yet, as when it is entered by hand) and is OData; the CSRF
  // switch is offered only where it applies and follows the import's default when auth is added.
  hasWrites: boolean | null;
  odata: boolean;
};

// The fields an API is called with: servers (one row each, so a refused one is marked at its row), the auth scheme
// with only the fields it needs and the CSRF switch, and the timeout. Shared by "Enter by hand" when adding and by
// the Details tab when editing.
export function RestDefinitionFields<D extends Omit<DefinitionEditDraft, "name">>({ draft, onChange, error, context = { hasWrites: null, odata: false } }: {
  draft: D;
  onChange: (next: D) => void;
  error: RestErrorView | null;
  context?: Context;
}) {
  const authFields = definitionAuthFields(draft.scheme);
  const set = (patch: Partial<D>) => onChange({ ...draft, ...patch });
  return (
    <>
      <ServerRowsField servers={draft.servers} error={error} onServers={(servers) => set({ servers } as Partial<D>)} />
      <div className="rst-grid">
        <Field label="Authentication" error={fieldError(error, "scheme")}>
          <select className="admin-panel__input" value={draft.scheme} onChange={(event) => onChange(withScheme(draft, event.target.value as AuthScheme, context.odata, context.hasWrites !== false))}
            data-testid="rest-add-scheme">
            {AUTH_SCHEMES.map((scheme) => <option key={scheme.value} value={scheme.value}>{scheme.label}</option>)}
          </select>
        </Field>
        <Field label="Timeout (seconds)" error={fieldError(error, "timeout")}>
          <input className="admin-panel__input" type="number" min={1} max={300} value={draft.timeout}
            onChange={(event) => set({ timeout: event.target.value } as Partial<D>)} data-testid="rest-def-timeout" />
        </Field>
      </div>
      {authFields.includes("header_name") ? (
        <Field label="Header name" hint="Defaults to X-API-Key." error={fieldError(error, "header_name")}>
          <input className="admin-panel__input" value={draft.headerName} onChange={(event) => set({ headerName: event.target.value } as Partial<D>)} placeholder="X-API-Key" />
        </Field>
      ) : null}
      {authFields.includes("query_name") ? (
        <Field label="Query parameter name" hint="Defaults to api_key.">
          <input className="admin-panel__input" value={draft.queryName} onChange={(event) => set({ queryName: event.target.value } as Partial<D>)} placeholder="api_key" />
        </Field>
      ) : null}
      {authFields.includes("token_url") ? (
        <Field label="Token URL">
          <input className="admin-panel__input" type="url" value={draft.tokenUrl} onChange={(event) => set({ tokenUrl: event.target.value } as Partial<D>)}
            placeholder="https://login.example.com/oauth/token" />
        </Field>
      ) : null}
      {authFields.includes("scopes") ? (
        <Field label="Scopes (optional)" hint="Separated by spaces or commas.">
          <input className="admin-panel__input" value={draft.scopes} onChange={(event) => set({ scopes: event.target.value } as Partial<D>)} />
        </Field>
      ) : null}
      <CsrfFields draft={draft} set={set} error={error} hasWrites={context.hasWrites} />
    </>
  );
}

// The servers, one row each: a refused one is marked at its row, a refusal without a row under the field.
function ServerRowsField({ servers, error, onServers }: {
  servers: string;
  error: RestErrorView | null;
  onServers: (servers: string) => void;
}) {
  const rows = servers.split("\n");
  const setRows = (next: string[]) => onServers(next.join("\n"));
  const errorRow = error?.field === "servers" && error.index !== undefined ? serverRowOfIndex(servers, error.index) : null;
  const serversError = error?.field === "servers" && errorRow === null ? error.text : null;
  return (
    <Field label="Servers" group hint="One base URL each; a connection can set its own." error={serversError} testId="rest-def-servers">
      {rows.map((row, index) => (
        <div key={index} className="rst-server-row" data-testid={`rest-def-server-${index}`}>
          <span className="rst-server-row__line">
            <input className="admin-panel__input" type="url" value={row} placeholder="https://api.example.com/v1" aria-label={`Server ${index + 1}`}
              aria-invalid={errorRow === index || undefined} onChange={(event) => setRows(rows.map((item, at) => (at === index ? event.target.value : item)))} />
            {rows.length > 1 ? (
              <button type="button" className="ds-btn ds-btn--ghost" aria-label={`Remove server ${index + 1}`}
                onClick={() => setRows(rows.filter((_, at) => at !== index))}>Remove</button>
            ) : null}
          </span>
          {errorRow === index ? <small className="rst-field__error" role="alert" data-testid="rest-def-server-error">{error?.text}</small> : null}
        </div>
      ))}
      <button type="button" className="ds-link-button rst-back" onClick={() => setRows([...rows, ""])} data-testid="rest-def-server-add">Add a server</button>
    </Field>
  );
}

// The CSRF switch where it applies, and the token header and fetch path while it is on.
function CsrfFields<D extends Omit<DefinitionEditDraft, "name">>({ draft, set, error, hasWrites }: {
  draft: D;
  set: (patch: Partial<D>) => void;
  error: RestErrorView | null;
  hasWrites: boolean | null;
}) {
  return (
    <>
    {csrfApplies(draft.scheme, hasWrites, draft.csrf) ? (
      <div className="admin-panel__field rst-field">
        <label className="admin-panel__checkbox">
          <input type="checkbox" checked={draft.csrf} disabled={draft.scheme === "none"} onChange={(event) => set({ csrf: event.target.checked } as Partial<D>)}
            data-testid="rest-def-csrf" />
          {CSRF_LABEL}
        </label>
        <small className="rst-hint">{CSRF_HINT}</small>
        {fieldError(error, "csrf") ? <small className="rst-field__error" role="alert">{fieldError(error, "csrf")}</small> : null}
      </div>
    ) : null}
    {draft.csrf && draft.scheme !== "none" ? (
      <div className="rst-grid" data-testid="rest-def-csrf-fields">
        <Field label="Token header" hint={CSRF_HEADER_HINT} error={fieldError(error, "csrf_header")}>
          <input className="admin-panel__input" value={draft.csrfHeader ?? ""} placeholder={CSRF_HEADER}
            onChange={(event) => set({ csrfHeader: event.target.value } as Partial<D>)} data-testid="rest-def-csrf-header" />
        </Field>
        <Field label="Token fetch path (optional)" hint={CSRF_FETCH_PATH_HINT} error={fieldError(error, "csrf_fetch_path")}>
          <input className="admin-panel__input" value={draft.csrfFetchPath ?? ""} placeholder="/sap/opu/odata/sap/API_X/"
            onChange={(event) => set({ csrfFetchPath: event.target.value } as Partial<D>)} data-testid="rest-def-csrf-fetch-path" />
        </Field>
      </div>
    ) : null}
    </>
  );
}
