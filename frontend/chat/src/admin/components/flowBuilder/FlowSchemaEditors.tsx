import type { FlowDefinitionNode } from "./flowBuilderTypes";

type JsonSchemaProperty = {
  type?: string;
  const?: unknown;
  enum?: unknown[];
  description?: string;
  properties?: Record<string, JsonSchemaProperty>;
  items?: JsonSchemaProperty;
};

type JsonObjectSchema = {
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
};

type ConfigSchemaFormProps = {
  schema?: Record<string, unknown>;
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
};

type NodeSchemaEditorProps = {
  node: FlowDefinitionNode;
  schemaKey: "input_schema" | "output_schema";
  onUpdate: (patch: Partial<FlowDefinitionNode>) => void;
};

const COMMON_SCHEMA_TYPES = ["string", "number", "integer", "boolean", "object", "array"];

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function asObjectSchema(schema?: Record<string, unknown>): JsonObjectSchema {
  return isObject(schema) ? (schema as JsonObjectSchema) : {};
}

function stringify(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function parseJson(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

function setNested(
  source: Record<string, unknown>,
  path: string[],
  value: unknown,
): Record<string, unknown> {
  const [head, ...tail] = path;
  if (!head) return source;
  if (!tail.length) {
    return { ...source, [head]: value };
  }
  const child = isObject(source[head]) ? source[head] : {};
  return { ...source, [head]: setNested(child, tail, value) };
}

function readNested(source: Record<string, unknown>, path: string[]): unknown {
  let current: unknown = source;
  for (const item of path) {
    if (!isObject(current)) return undefined;
    current = current[item];
  }
  return current;
}

function inputTypeFor(property: JsonSchemaProperty): string {
  if (property.type === "integer" || property.type === "number") return "number";
  if (property.type === "boolean") return "checkbox";
  return "text";
}

function parsePrimitive(raw: string, property: JsonSchemaProperty): unknown {
  if (property.type === "integer") return raw === "" ? undefined : Number.parseInt(raw, 10);
  if (property.type === "number") return raw === "" ? undefined : Number(raw);
  return raw;
}

function ConfigField({
  name,
  property,
  value,
  required,
  onChange,
}: {
  name: string;
  property: JsonSchemaProperty;
  value: unknown;
  required: boolean;
  onChange: (value: unknown) => void;
}) {
  if (property.const !== undefined) {
    return (
      <label className="flow-inspector__schema-field">
        <span>{name}</span>
        <input className="flow-inspector__input" value={String(property.const)} readOnly />
      </label>
    );
  }

  if (property.enum?.length) {
    return (
      <label className="flow-inspector__schema-field">
        <span>
          {name}
          {required ? <strong>*</strong> : null}
        </span>
        <select
          className="flow-inspector__select"
          value={String(value ?? "")}
          onChange={(event) => onChange(event.target.value || undefined)}
        >
          <option value="">inherit / empty</option>
          {property.enum.map((item) => (
            <option key={String(item)} value={String(item)}>
              {String(item)}
            </option>
          ))}
        </select>
      </label>
    );
  }

  if (property.type === "object" || property.type === "array" || property.properties) {
    return (
      <label className="flow-inspector__schema-field">
        <span>
          {name}
          {required ? <strong>*</strong> : null}
        </span>
        <textarea
          className="flow-inspector__config flow-inspector__config--compact"
          rows={4}
          value={stringify(value)}
          onChange={(event) => onChange(parseJson(event.target.value))}
        />
      </label>
    );
  }

  if (property.type === "boolean") {
    return (
      <label className="flow-inspector__schema-field flow-inspector__schema-field--check">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span>
          {name}
          {required ? <strong>*</strong> : null}
        </span>
      </label>
    );
  }

  return (
    <label className="flow-inspector__schema-field">
      <span>
        {name}
        {required ? <strong>*</strong> : null}
      </span>
      <input
        className="flow-inspector__input"
        type={inputTypeFor(property)}
        value={stringify(value)}
        onChange={(event) => onChange(parsePrimitive(event.target.value, property))}
      />
      {property.description ? <small>{property.description}</small> : null}
    </label>
  );
}

export function ConfigSchemaForm({ schema, config, onChange }: ConfigSchemaFormProps) {
  const objectSchema = asObjectSchema(schema);
  const properties = objectSchema.properties ?? {};
  const required = new Set(objectSchema.required ?? []);
  const entries = Object.entries(properties);
  if (!entries.length) return null;

  return (
    <div className="flow-inspector__section">
      <div className="flow-inspector__section-title">Config fields</div>
      <div className="flow-inspector__schema-fields">
        {entries.map(([key, property]) => {
          if (key === "arguments" && property.properties) {
            return (
              <div key={key} className="flow-inspector__schema-nested">
                <div className="flow-inspector__section-title">Arguments</div>
                {Object.entries(property.properties).map(([nestedKey, nestedProperty]) => (
                  <ConfigField
                    key={nestedKey}
                    name={nestedKey}
                    property={nestedProperty}
                    value={readNested(config, [key, nestedKey])}
                    required={required.has(key)}
                    onChange={(value) => onChange(setNested(config, [key, nestedKey], value))}
                  />
                ))}
              </div>
            );
          }
          return (
            <ConfigField
              key={key}
              name={key}
              property={property}
              value={config[key]}
              required={required.has(key)}
              onChange={(value) => onChange({ ...config, [key]: value })}
            />
          );
        })}
      </div>
    </div>
  );
}

export function NodeSchemaEditor({ node, schemaKey, onUpdate }: NodeSchemaEditorProps) {
  const schema = node[schemaKey] ?? {};
  const title = schemaKey === "input_schema" ? "Input schema" : "Output schema";

  function updateField(oldKey: string, nextKey: string, nextType: string) {
    const updated = { ...schema };
    if (oldKey !== nextKey) {
      delete updated[oldKey];
    }
    if (nextKey.trim()) {
      updated[nextKey.trim()] = nextType.trim() || "string";
    }
    onUpdate({ [schemaKey]: updated });
  }

  function deleteField(key: string) {
    const updated = { ...schema };
    delete updated[key];
    onUpdate({ [schemaKey]: updated });
  }

  function addField() {
    let index = Object.keys(schema).length + 1;
    let key = `field_${index}`;
    while (schema[key]) {
      index += 1;
      key = `field_${index}`;
    }
    onUpdate({ [schemaKey]: { ...schema, [key]: "string" } });
  }

  return (
    <div className="flow-inspector__section">
      <div className="flow-inspector__schema-editor-head">
        <span className="flow-inspector__section-title">{title}</span>
        <button type="button" onClick={addField}>
          Add
        </button>
      </div>
      <div className="flow-inspector__schema-editor">
        {Object.entries(schema).map(([key, type]) => (
          <div key={key} className="flow-inspector__schema-row">
            <input
              className="flow-inspector__input"
              value={key}
              onChange={(event) => updateField(key, event.target.value, String(type))}
            />
            <input
              className="flow-inspector__input"
              list="flow-schema-types"
              value={String(type)}
              onChange={(event) => updateField(key, key, event.target.value)}
            />
            <button type="button" onClick={() => deleteField(key)}>
              Delete
            </button>
          </div>
        ))}
        {!Object.keys(schema).length ? (
          <p className="flow-inspector__hint">No fields defined.</p>
        ) : null}
      </div>
      <datalist id="flow-schema-types">
        {COMMON_SCHEMA_TYPES.map((type) => (
          <option key={type} value={type} />
        ))}
      </datalist>
    </div>
  );
}
