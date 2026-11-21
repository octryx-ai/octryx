import { SecretRebindFieldHint } from "../../secretRebind/SecretRebindFieldHint";
import { rebindFieldClass } from "../../secretRebind/secretRebindFlow";
import type { ConnectorSecretRebind } from "../../secretRebind/useConnectorSecretRebind";
import { connectorFieldInputId } from "../../secretRebind/useConnectorSecretRebind";
import { ConnectorFieldGroup } from "./ConnectorFieldGroup";
import { GROUP_TITLES, fieldLabel, groupedFields } from "./connectorFieldGroupsModel";

type ConfiguredConnectorFieldsPanelProps = {
  connector: any;
  draft: Record<string, any>;
  ctx: Record<string, unknown>;
  rebind: ConnectorSecretRebind;
  // false: the fields are shown as one list inside a group the caller renders (guided forms).
  grouped?: boolean;
};

const KNOWLEDGE_JSON_FIELDS = new Set([
  "knowledge_import_scope",
  "knowledge_import_limits",
  "knowledge_import_retention",
]);

const BOOL_FIELDS = new Set([
  "k8s_use_kubectl",
  "k8s_verify_tls",
  "knowledge_import_enabled",
]);

function isJsonField(field: string) {
  return (
    field.includes("_allowed_") ||
    field.includes("_repos") ||
    field.includes("_spaces") ||
    field.includes("_pages") ||
    KNOWLEDGE_JSON_FIELDS.has(field)
  );
}

// A JSON list or object field, in words (delivery 5: no raw JSON example in the main view).
function jsonHintFor(field: string) {
  if (field === "jira_allowed_projects") return "A list of project keys; empty: no restriction.";
  if (KNOWLEDGE_JSON_FIELDS.has(field)) return "Import settings, stored as JSON.";
  return "A list, stored as JSON.";
}

function boolFieldChecked(draft: Record<string, any>, field: string) {
  if (draft[field] !== undefined) {
    return String(draft[field] ?? "").toLowerCase() === "true";
  }
  return false;
}

type ConnectorFieldControlProps = {
  connector: any;
  field: string;
  draft: Record<string, any>;
  rebind: ConnectorSecretRebind;
  isSecret: boolean;
  isJson: boolean;
  isBool: boolean;
  hasStoredSecret: unknown;
  onSet: (value: string) => void;
};

/** The field's control: a checkbox, the import frequency, a JSON text area or a text or secret input. */
function ConnectorFieldControl({
  connector, field, draft, rebind, isSecret, isJson, isBool, hasStoredSecret, onSet,
}: ConnectorFieldControlProps) {
  return isBool ? (
    <label className="connector-field connector-field--checkbox">
      <input
        type="checkbox"
        checked={boolFieldChecked(draft, field)}
        onChange={(e) =>
          onSet(e.target.checked ? "true" : "false")
        }
      />
      <span>Enabled</span>
    </label>
  ) : field === "knowledge_import_frequency" ? (
    <select
      className="connector-field__input"
      value={draft[field] ?? "hourly"}
      onChange={(e) =>
        onSet(e.target.value)
      }
    >
      <option value="hourly">Hourly</option>
      <option value="manual">Manual</option>
    </select>
  ) : isJson ? (
    <textarea
      id={connectorFieldInputId(connector.tool_name, field)}
      className="connector-field__input connector-field__input--textarea"
      value={draft[field] ?? ""}
      onChange={(e) =>
        onSet(e.target.value)
      }
      aria-describedby={`${connectorFieldInputId(connector.tool_name, field)}-hint`}
      rows={4}
      spellCheck={false}
    />
  ) : (
    <input
      id={connectorFieldInputId(connector.tool_name, field)}
      type={isSecret ? "password" : "text"}
      className={`connector-field__input${rebindFieldClass(rebind.flow, field)}`}
      value={draft[field] ?? ""}
      onChange={(e) =>
        onSet(e.target.value)
      }
      placeholder={
        isSecret && hasStoredSecret
          ? "••••••• (stored — leave blank to keep)"
          : ""
      }
      autoComplete="off"
    />
  );
}

export function ConfiguredConnectorFieldsPanel({
  connector,
  draft,
  ctx,
  rebind,
  grouped = true,
}: ConfiguredConnectorFieldsPanelProps) {
  const { setConnectorField: setDraftField } = ctx as Record<string, any>;
  const setConnectorField = (toolName: string, field: string, value: string) => {
    setDraftField(toolName, field, value);
    rebind.fieldEdited(field);
  };

  const renderField = (field: string) => {
    const isSecret = connector.secret_fields.includes(field);
    const isJson = isJsonField(field);
    const isBool = BOOL_FIELDS.has(field);
    const hasStoredSecret = isSecret && connector.secret_status[field];

    return (
      <div key={field} className="connector-field">
        <label className="connector-field__label" htmlFor={isBool ? undefined : connectorFieldInputId(connector.tool_name, field)}>
          {fieldLabel(connector.tool_name, field)}
          {isSecret ? (
            <span className="connector-field__secret-badge">secret</span>
          ) : null}
        </label>
        <ConnectorFieldControl connector={connector} field={field} draft={draft} rebind={rebind} isSecret={isSecret}
          isJson={isJson} isBool={isBool} hasStoredSecret={hasStoredSecret}
          onSet={(value) => setConnectorField(connector.tool_name, field, value)} />
        {isJson ? (
          <span className="admin-panel__hint" id={`${connectorFieldInputId(connector.tool_name, field)}-hint`}>
            {jsonHintFor(field)}
          </span>
        ) : null}
        <SecretRebindFieldHint flow={rebind.flow} field={field} />
      </div>
    );
  };

  const fields: string[] = connector.fields || [];
  if (!grouped) return <div className="connector-card__fields">{fields.map(renderField)}</div>;
  // Delivery 5: Connection, Authentication, Scope, Settings, each with its title.
  return (
    <>
      {groupedFields(fields, connector.secret_fields || []).map(({ group, fields: members }) => (
        <ConnectorFieldGroup key={group} group={group} title={GROUP_TITLES[group]}>
          <div className="connector-card__fields">{members.map(renderField)}</div>
        </ConnectorFieldGroup>
      ))}
    </>
  );
}
