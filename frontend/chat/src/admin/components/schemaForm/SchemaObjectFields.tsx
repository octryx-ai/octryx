import { SchemaField, type WidgetProps } from "./SchemaField";
import { defaultValueFor } from "./schemaDefaults";
import { useSchemaFormContext } from "./schemaFormContext";
import type { JsonSchema } from "./schemaFormTypes";
import { escapePointerSegment, joinPointer, setAtPointer } from "./schemaPointer";
import { fieldOrder, humanizeKey, isRecord, requiredSet } from "./schemaResolve";
import { controlClass, inlineLabel } from "./schemaWidgets";
import { discriminatorProperty, pickOneOfBranch, switchUnionVariant, unionVariantList } from "./schemaUnion";

interface ObjectBodyProps {
  pointer: string;
  schema: JsonSchema;
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  hidden?: readonly string[];
}

/** The property fields of an object schema, required first. Unknown keys are shown, never dropped. */
export function SchemaObjectBody({ pointer, schema, value, onChange, hidden = [] }: ObjectBodyProps) {
  const properties = isRecord(schema.properties) ? schema.properties : {};
  const required = requiredSet(schema);
  const keys = fieldOrder(schema).filter((key) => !hidden.includes(key));
  const unknown = Object.keys(value).filter((key) => !(key in properties) && !hidden.includes(key));
  return (
    <div className="schema-form__fields">
      {keys.map((key) => (
        <SchemaField
          key={key}
          pointer={joinPointer(pointer, key)}
          name={key}
          schema={properties[key] as JsonSchema}
          required={required.has(key)}
          value={value[key]}
          onChange={(next) => onChange(setAtPointer(value, `/${escapePointerSegment(key)}`, next))}
        />
      ))}
      {unknown.length ? (
        <div className="schema-form__unsupported">
          <p className="schema-form__help">Fields not described by the schema; shown read-only.</p>
          <pre className="schema-form__preview">{JSON.stringify(Object.fromEntries(unknown.map((key) => [key, value[key]])), null, 2)}</pre>
        </div>
      ) : null}
    </div>
  );
}

export function SchemaObjectWidget({ model, value, onChange }: WidgetProps) {
  const { root, disabled } = useSchemaFormContext();
  const optional = model.nullable || !model.required;
  if (!isRecord(value) && optional) {
    return disabled ? (
      <p className="schema-form__help">Not set.</p>
    ) : (
      <button type="button" className="admin-panel__action-btn schema-form__add" onClick={() => onChange(defaultValueFor(root, model.schema) ?? {})}>
        {`Add ${inlineLabel(model.label)}`}
      </button>
    );
  }
  const current = isRecord(value) ? value : {};
  return (
    <>
      <SchemaObjectBody pointer={model.pointer} schema={model.schema} value={current} onChange={onChange} />
      {optional && !disabled ? (
        <div className="schema-form__actions">
          <button type="button" className="admin-panel__action-btn" onClick={() => onChange(undefined)}>
            {`Remove ${inlineLabel(model.label)}`}
          </button>
        </div>
      ) : null}
    </>
  );
}

export function SchemaUnionWidget(props: WidgetProps) {
  const { root, disabled } = useSchemaFormContext();
  const { model, value, onChange, id } = props;
  const variants = unionVariantList(root, model.schema);
  const picked = pickOneOfBranch(root, model.schema, value);
  const tagProperty = discriminatorProperty(model.schema);
  const selectId = `${id}-variant`;
  const branch = picked?.branch;
  const constKeys = branch && isRecord(branch.properties)
    ? Object.entries(branch.properties).filter(([, schema]) => isRecord(schema) && "const" in schema).map(([key]) => key)
    : [];
  const hidden = tagProperty ? [tagProperty, ...constKeys] : constKeys;
  return (
    <>
      <div className="schema-form__field">
        <label className="schema-form__label" htmlFor={selectId}>
          {tagProperty ? humanizeKey(tagProperty) : "Variant"}
        </label>
        <select
          id={selectId}
          className={controlClass(props)}
          aria-describedby={props.describedBy}
          aria-invalid={props.invalid || undefined}
          value={picked ? String(picked.index) : ""}
          disabled={disabled}
          onChange={(event) => {
            const raw = event.target.value;
            if (raw === "") {
              onChange(undefined);
              return;
            }
            onChange(switchUnionVariant(root, variants[Number(raw)].branch, value));
          }}
        >
          <option value="" disabled={model.required && value !== undefined}>
            {model.required ? "Select…" : "Not set"}
          </option>
          {variants.map((variant) => (
            <option key={variant.index} value={String(variant.index)}>
              {variant.label}
            </option>
          ))}
        </select>
      </div>
      {branch && isRecord(branch.properties) ? (
        <SchemaObjectBody
          pointer={model.pointer}
          schema={branch}
          value={isRecord(value) ? value : {}}
          onChange={onChange}
          hidden={hidden}
        />
      ) : picked && !("const" in picked.branch) ? (
        <SchemaField pointer={model.pointer} name={model.key} label={variants[picked.index].label} schema={picked.branch} required={model.required} value={value} onChange={onChange} />
      ) : null}
    </>
  );
}
