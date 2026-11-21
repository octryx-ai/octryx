import type { Dispatch, ReactNode, SetStateAction } from "react";
import type { AdminChannelConfigFieldRow } from "./channelTypes";

type AdminChannelConfigFieldsProps = {
  configFields: AdminChannelConfigFieldRow[];
  channelConfigJson: string;
  setChannelConfigJson: (value: string) => void;
  channelFormValues: Record<string, unknown>;
  setChannelFormValues: Dispatch<SetStateAction<Record<string, unknown>>>;
  secretFields?: Record<string, { has_value: boolean }>;
};

function toFieldLabel(value: string) {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function isSecretField(field: AdminChannelConfigFieldRow) {
  const name = field.name.toLowerCase();
  return (
    Boolean(field.secret) ||
    name.includes("token") ||
    name.includes("secret") ||
    name.includes("password") ||
    name.includes("key")
  );
}

export function AdminChannelConfigFields({
  configFields,
  channelConfigJson,
  setChannelConfigJson,
  channelFormValues,
  setChannelFormValues,
  secretFields = {},
}: AdminChannelConfigFieldsProps) {
  if (configFields.length === 0) {
    return (
      <textarea
        className="admin-panel__form-input"
        rows={10}
        value={channelConfigJson}
        onChange={(event) => setChannelConfigJson(event.target.value)}
        style={{ fontFamily: "monospace", fontSize: "var(--ds-text-sm)" }}
      />
    );
  }

  return (
    <div className="admin-panel__stack">
      {configFields.map((field) => (
        <ChannelConfigField
          key={field.name}
          field={field}
          value={channelFormValues[field.name]}
          setChannelFormValues={setChannelFormValues}
          secretFields={secretFields}
        />
      ))}
    </div>
  );
}

type FieldProps = {
  field: AdminChannelConfigFieldRow;
  value: unknown;
  setChannelFormValues: Dispatch<SetStateAction<Record<string, unknown>>>;
  secretFields: Record<string, { has_value: boolean }>;
};

function ChannelConfigField({ field, value, setChannelFormValues, secretFields }: FieldProps) {
  const fieldLabel = toFieldLabel(field.name);
  const required = field.required ? (
    <span className="admin-form-field__required"> *</span>
  ) : null;

  return (
    <div className="admin-form-field">
      {field.type === "boolean" ? (
        <BooleanField field={field} value={value} setChannelFormValues={setChannelFormValues} fieldLabel={fieldLabel} required={required} />
      ) : (
        <>
          <label className="admin-form-field__label">
            {fieldLabel}
            {required}
          </label>
          <FieldInput field={field} value={value} setChannelFormValues={setChannelFormValues} secretFields={secretFields} />
        </>
      )}
      {field.type !== "boolean" && field.description ? (
        <div
          className="admin-panel__cell--muted"
          style={{ fontSize: "var(--ds-text-xs)" }}
        >
          {field.description}
        </div>
      ) : null}
    </div>
  );
}

function BooleanField({
  field,
  value,
  setChannelFormValues,
  fieldLabel,
  required,
}: Omit<FieldProps, "secretFields"> & { fieldLabel: string; required: ReactNode }) {
  return (
    <label className="admin-form-toggle-row">
      <div className="admin-form-toggle-copy">
        <span>
          {fieldLabel}
          {required}
        </span>
        {field.description ? (
          <div className="admin-form-help">{field.description}</div>
        ) : null}
      </div>
      <span
        className={`toggle-switch ${Boolean(value) ? "toggle-switch--on" : ""}`}
        onClick={() =>
          setChannelFormValues((prev) => ({
            ...prev,
            [field.name]: !Boolean(value),
          }))
        }
        role="switch"
        aria-checked={Boolean(value)}
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === " " || event.key === "Enter") {
            setChannelFormValues((prev) => ({
              ...prev,
              [field.name]: !Boolean(value),
            }));
          }
        }}
      />
    </label>
  );
}

// Each kind returns its element directly (no wrapper component), so an input is reused when a field changes kind.
function FieldInput({ field, value, setChannelFormValues, secretFields }: FieldProps) {
  const update = (next: unknown) => setChannelFormValues((prev) => ({ ...prev, [field.name]: next }));
  const shown = value === undefined || value === null ? "" : String(value);
  if (field.type === "number") {
    return (
      <input
        type="number"
        className="admin-panel__form-input"
        value={shown}
        onChange={(event) => update(event.target.value === "" ? "" : Number(event.target.value))}
      />
    );
  }
  if (field.type === "select" && field.options) {
    return (
      <select className="admin-panel__form-input" value={shown} onChange={(event) => update(event.target.value)}>
        {field.options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    );
  }
  if (field.type === "list") {
    return (
      <input
        type="text"
        className="admin-panel__form-input"
        placeholder="comma-separated values"
        value={Array.isArray(value) ? (value as string[]).join(", ") : shown}
        onChange={(event) => update(event.target.value.split(",").map((entry) => entry.trim()).filter(Boolean))}
      />
    );
  }
  const secret = isSecretField(field);
  return (
    <input
      type={secret ? "password" : "text"}
      autoComplete={secret ? "new-password" : undefined}
      className="admin-panel__form-input"
      placeholder={secret && secretFields[field.name]?.has_value ? "Stored. Leave empty to keep it." : undefined}
      value={shown}
      onChange={(event) => update(event.target.value)}
    />
  );
}
