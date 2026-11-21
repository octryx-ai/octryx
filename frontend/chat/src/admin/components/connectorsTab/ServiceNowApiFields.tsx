import type { ConnectorSecretRebind } from "../../secretRebind/useConnectorSecretRebind";
import { CredentialInput, Option } from "./ConnectorCredentialInput";
import type { CredentialFieldError } from "./ConnectorCredentialInput";
import { API_STYLE_FIELD, API_STYLE_TEXT, PAGE_SIZE_DEFAULT, PAGE_SIZE_FIELD, PAGE_SIZE_MAX, SCRIPTED_PATHS } from "./serviceNowApiModel";
import type { ServiceNowApiStyle, ServiceNowApiView } from "./serviceNowApiModel";

// The "API" section of the ServiceNow form: Standard Table API or the organisation's Scripted REST API, with
// the scripted endpoints' paths and page size. Placeholders are neutral: no namespace or API id is suggested.
export function ServiceNowApiFields({ view, draft, set, shown, id, rebind }: {
  view: ServiceNowApiView;
  draft: Record<string, string>;
  set: (field: string, value: string) => void;
  shown: (field: string) => CredentialFieldError | null;
  id: (field: string) => string;
  rebind: Pick<ConnectorSecretRebind, "flow">;
}) {
  return (
    <>
      <div className="connector-field jira-setup__group" role="radiogroup" aria-labelledby={`${id(API_STYLE_FIELD)}-label`}
        data-testid="servicenow-api">
        <span id={`${id(API_STYLE_FIELD)}-label`} className="connector-field__label">API</span>
        <div className="jira-setup__options">
          {(["table", "scripted"] as ServiceNowApiStyle[]).map((style) => (
            <Option key={style} name={id(API_STYLE_FIELD)} value={style} checked={view.style === style}
              onChoose={() => set(API_STYLE_FIELD, style)} title={API_STYLE_TEXT[style].label} help={API_STYLE_TEXT[style].help} />
          ))}
        </div>
      </div>
      {view.style === "scripted" ? (
        <>
          {SCRIPTED_PATHS.map((path) => (
            <CredentialInput key={path.field} field={path.field} label={path.label} type="text" value={draft[path.field] ?? ""}
              placeholder={path.placeholder} help={path.endpoint === "journal" ? "Only when your API offers incident comments and work notes." : undefined}
              error={shown(path.field)} id={id} rebind={rebind} onChange={set} />
          ))}
          <CredentialInput field={PAGE_SIZE_FIELD} label="Page size" type="number" value={draft[PAGE_SIZE_FIELD] ?? ""}
            placeholder={String(PAGE_SIZE_DEFAULT)} help={`Records per request (default ${PAGE_SIZE_DEFAULT}, at most ${PAGE_SIZE_MAX}).`}
            error={shown(PAGE_SIZE_FIELD)} id={id} rebind={rebind} onChange={set} />
        </>
      ) : null}
    </>
  );
}
