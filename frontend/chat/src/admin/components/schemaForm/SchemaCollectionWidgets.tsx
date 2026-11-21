import { useState } from "react";

import { SchemaField, type WidgetProps } from "./SchemaField";
import { newEntryValue } from "./schemaDefaults";
import { useSchemaFormContext } from "./schemaFormContext";
import type { JsonSchema } from "./schemaFormTypes";
import { escapePointerSegment, joinPointer, setAtPointer } from "./schemaPointer";
import { isRecord, mapValueSchema, normalizeField } from "./schemaResolve";
import { controlClass, emptyCollectionValue, inlineLabel, mapKeyProblem, parseTagInput } from "./schemaWidgets";

function itemSchema(model: WidgetProps["model"]): JsonSchema {
  return isRecord(model.schema.items) ? model.schema.items : {};
}

function listValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function SchemaTagsWidget(props: WidgetProps) {
  const { root, disabled } = useSchemaFormContext();
  const { model, value, onChange, id } = props;
  const [draft, setDraft] = useState("");
  const items = listValue(value);
  const itemKind = normalizeField(root, itemSchema(model)).schema.type;
  const parsed = parseTagInput(draft, itemKind);
  const add = () => {
    if (parsed === undefined) return;
    onChange([...items, parsed]);
    setDraft("");
  };
  return (
    <div className="schema-form__tags" id={disabled ? id : undefined} aria-describedby={disabled ? props.describedBy : undefined}>
      {items.length ? (
        <ul className="schema-form__chips" aria-label={model.label}>
          {items.map((item, index) => (
            <li key={`${index}-${String(item)}`} className="schema-form__chip">
              <span>{typeof item === "string" ? item : JSON.stringify(item)}</span>
              {!disabled ? (
                <button
                  type="button"
                  className="schema-form__chip-remove"
                  aria-label={`Remove ${typeof item === "string" ? item : JSON.stringify(item)}`}
                  onClick={() => onChange(emptyCollectionValue(items.filter((_, other) => other !== index), model.required))}
                >
                  ×
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : disabled ? (
        <p className="schema-form__help">None.</p>
      ) : null}
      {!disabled ? (
        <div className="schema-form__row">
          <input
            id={id}
            type={itemKind === "number" || itemKind === "integer" ? "number" : "text"}
            className={controlClass(props)}
            aria-describedby={props.describedBy}
            aria-invalid={props.invalid || undefined}
            value={draft}
            placeholder={model.placeholder ?? "Add value"}
            spellCheck={model.mono ? false : undefined}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                add();
              }
            }}
          />
          <button type="button" className="admin-panel__action-btn" disabled={parsed === undefined} onClick={add}>
            Add
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function SchemaChecklistWidget(props: WidgetProps) {
  const { root, disabled } = useSchemaFormContext();
  const { model, value, onChange, id } = props;
  const items = listValue(value);
  const options = normalizeField(root, itemSchema(model)).schema.enum;
  const choices = Array.isArray(options) ? options : [];
  return (
    <div className="schema-form__checklist" role="group" aria-describedby={props.describedBy}>
      {choices.map((option, index) => (
        <label key={JSON.stringify(option)} className="schema-form__check">
          <input
            id={index === 0 ? id : undefined}
            type="checkbox"
            className="schema-form__checkbox"
            checked={items.includes(option)}
            disabled={disabled}
            onChange={(event) => {
              const next = event.target.checked ? choices.filter((choice) => choice === option || items.includes(choice)) : items.filter((item) => item !== option);
              onChange(emptyCollectionValue(next, model.required));
            }}
          />
          <span className="schema-form__label">{typeof option === "string" ? option : JSON.stringify(option)}</span>
        </label>
      ))}
    </div>
  );
}

export function SchemaItemsWidget({ model, value, onChange }: WidgetProps) {
  const { root, disabled } = useSchemaFormContext();
  const items = listValue(value);
  const schema = itemSchema(model);
  return (
    <div className="schema-form__items">
      {items.map((item, index) => (
        <div key={index} className="schema-form__item">
          <SchemaField
            pointer={joinPointer(model.pointer, index)}
            name={`${model.label} ${index + 1}`}
            label={`${model.label} ${index + 1}`}
            schema={schema}
            required
            value={item}
            onChange={(next) => onChange(setAtPointer({ list: items }, `/list/${index}`, next).list)}
          />
          {!disabled ? (
            <div className="schema-form__actions">
              <button
                type="button"
                className="admin-panel__action-btn"
                onClick={() => onChange(emptyCollectionValue(items.filter((_, other) => other !== index), model.required))}
              >
                {`Remove ${inlineLabel(model.label)} ${index + 1}`}
              </button>
            </div>
          ) : null}
        </div>
      ))}
      {!disabled ? (
        <button type="button" className="admin-panel__action-btn schema-form__add" onClick={() => onChange([...items, newEntryValue(root, schema)])}>
          {`Add ${inlineLabel(model.label)}`}
        </button>
      ) : items.length ? null : (
        <p className="schema-form__help">None.</p>
      )}
    </div>
  );
}

export function SchemaMapWidget(props: WidgetProps) {
  const { root, disabled } = useSchemaFormContext();
  const { model, value, onChange, id } = props;
  const [draftKey, setDraftKey] = useState("");
  const entries = isRecord(value) ? value : {};
  const valueSchema = mapValueSchema(model.schema) ?? {};
  const problem = draftKey ? mapKeyProblem(model.schema, draftKey, Object.keys(entries)) : undefined;
  const add = () => {
    if (!draftKey || problem) return;
    onChange({ ...entries, [draftKey]: newEntryValue(root, valueSchema) });
    setDraftKey("");
  };
  return (
    <div className="schema-form__map">
      {Object.keys(entries).map((key) => (
        <div key={key} className="schema-form__item">
          <SchemaField
            pointer={joinPointer(model.pointer, key)}
            name={key}
            label={key}
            schema={valueSchema}
            required
            value={entries[key]}
            onChange={(next) => onChange(emptyCollectionValue(setAtPointer(entries, `/${escapePointerSegment(key)}`, next), model.required))}
          />
          {!disabled ? (
            <div className="schema-form__actions">
              <button
                type="button"
                className="admin-panel__action-btn"
                onClick={() => onChange(emptyCollectionValue(setAtPointer(entries, `/${escapePointerSegment(key)}`, undefined), model.required))}
              >
                {`Remove ${key}`}
              </button>
            </div>
          ) : null}
        </div>
      ))}
      {!disabled ? (
        <div className="schema-form__field">
          <div className="schema-form__row">
            <input
              id={id}
              type="text"
              className={controlClass({ model: { ...model, mono: true }, invalid: Boolean(problem) })}
              aria-label={`New ${inlineLabel(model.label)} key`}
              aria-describedby={problem ? `${id}-key-problem` : props.describedBy}
              aria-invalid={Boolean(problem) || undefined}
              value={draftKey}
              placeholder="New key"
              spellCheck={false}
              onChange={(event) => setDraftKey(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  add();
                }
              }}
            />
            <button type="button" className="admin-panel__action-btn" disabled={!draftKey || Boolean(problem)} onClick={add}>
              Add entry
            </button>
          </div>
          {problem ? (
            <p id={`${id}-key-problem`} className="schema-form__error">
              {problem}
            </p>
          ) : null}
        </div>
      ) : Object.keys(entries).length ? null : (
        <p className="schema-form__help">None.</p>
      )}
    </div>
  );
}
