import { CredentialInput, FieldError } from "../connectorsTab/ConnectorCredentialInput";
import { connectorFieldInputId } from "../../secretRebind/useConnectorSecretRebind";
import { accessLabel, accessOptionLabel } from "../connections/authFields";
import { authLabel } from "../connections/connectionTypes";
import type { FieldsView } from "./namedFieldsModel";
import type { NamedDescriptor } from "./namedConnectionsTypes";

type Props = {
  descriptor: NamedDescriptor;
  draft: Record<string, string>;
  view: FieldsView;
  set: (field: string, value: string) => void;
  showAllErrors: boolean;
};

const NO_REBIND = { flow: null };

// The generic sign-in of a named connection (delivery 3): one input per descriptor field, by kind. A secret is
// write-only ("Stored · leave empty to keep"); a list is comma separated; a yes/no field is a choice.
export function NamedFieldsForm({ descriptor, draft, view, set, showAllErrors }: Props) {
  const toolName = `${descriptor.connector}-named`;
  const id = (field: string) => connectorFieldInputId(toolName, field);
  const shown = (field: string) => {
    const error = view.errors[field];
    return error && (error.live || showAllErrors) ? error : null;
  };
  return (
    <>
      {descriptor.fields.map((described) => ({ ...described, label: accessLabel(descriptor.connector, described.name, draft, described.label) })).map((field) => {
        if (field.kind === "bool" || field.kind === "select") {
          const options = field.kind === "bool" ? ["true", "false"] : field.options;
          return (
            <div className="connector-field" key={field.name}>
              <label className="connector-field__label" htmlFor={id(field.name)}>{field.label}</label>
              <select id={id(field.name)} className="connector-field__input" value={draft[field.name] ?? ""}
                onChange={(event) => set(field.name, event.target.value)}>
                <option value="">{field.kind === "bool" ? "Not set" : "Choose…"}</option>
                {options.map((option) => (
                  <option key={option} value={option}>
                    {field.kind === "bool" ? (option === "true" ? "Yes" : "No")
                      : accessOptionLabel(descriptor.connector, field.name, option) ?? authLabel(option)}
                  </option>
                ))}
              </select>
              <FieldError error={shown(field.name)} />
            </div>
          );
        }
        const secret = field.kind === "secret";
        const placeholder = secret && view.keepable[field.name]
          ? "Stored · leave empty to keep"
          : field.placeholder || (field.kind === "list" ? "comma separated" : "");
        return (
          <CredentialInput key={field.name} field={field.name} label={field.label}
            type={secret ? "password" : field.kind === "url" ? "url" : "text"} secret={secret}
            value={draft[field.name] ?? ""} placeholder={placeholder} error={shown(field.name)} id={id}
            rebind={NO_REBIND} onChange={set} />
        );
      })}
    </>
  );
}
