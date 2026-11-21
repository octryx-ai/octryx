// Typed value editor of one If / else rule: value type choice, value input and the kept-as-saved case.
import { useState } from "react";
import {
  operatorValueTypes,
  parseTypedValue,
  valueText,
  valueTypeOf,
  VALUE_TYPE_LABELS,
  type RuleCondition,
  type ValueType,
} from "./flowConditionalBranches";

type ValueEditorProps = {
  condition: Extract<RuleCondition, { form: "operator" }>;
  onValue: (value: unknown) => void;
};

// `seen`: the stored value at the last render; `written`: the value this editor last wrote.
type ValueState = { type: ValueType | "keep"; draft: string; invalid: boolean; seen: string; written: string | null };

// Identity of an authored value; undefined is distinct from every JSON value.
const valueIdentity = (value: unknown) => (value === undefined ? "\u0000undefined" : JSON.stringify(value));

function stateFor(condition: ValueEditorProps["condition"]): ValueState {
  const type = valueTypeOf(condition.value, condition.operator);
  return { type, draft: valueText(condition.value, type), invalid: false, seen: valueIdentity(condition.value), written: null };
}

// The value of one rule under an explicit type. The type is the author's choice; text is never
// re-read as a number or a list on its own. A saved value no type can show is kept as it is.
// The local draft follows the authored value: what the author types (also an unfinished or
// invalid entry) stays while the stored value is unchanged or becomes the value this editor wrote;
// any other change of the stored value (undo/redo, another step or rule) shows it again.
export function RuleValueEditor({ condition, onValue }: ValueEditorProps) {
  const allowed = operatorValueTypes(condition.operator);
  const [state, setState] = useState<ValueState>(() => stateFor(condition));
  let current = state;
  const stored = valueIdentity(condition.value);
  if (stored !== state.seen) {
    current = stored === state.written ? { ...state, seen: stored } : stateFor(condition);
    setState(current);
  }
  const { type, draft, invalid } = current;

  if (type === "keep") {
    return (
      <div className="flow-inspector__schema-field">
        <span>Value</span>
        <code className="flow-conditional__kept" data-testid="router-rule-value-kept">{draft}</code>
        <div className="flow-conditional__note">This value is kept exactly as saved; this editor cannot show its type.</div>
        <button type="button" className="flow-conditional__button" onClick={() => setState((prev) => ({ ...prev, type: allowed[0] ?? "text", draft: "", invalid: false }))}>
          Replace with a new value
        </button>
      </div>
    );
  }

  const types = allowed.includes(type) || !allowed.length ? (allowed.length ? allowed : [type]) : [...allowed, type];
  const commit = (text: string, nextType: ValueType) => {
    const parsed = parseTypedValue(text, nextType);
    setState((prev) => ({
      ...prev,
      type: nextType,
      draft: text,
      invalid: parsed === null,
      // When the stored value comes back as this one, the draft (e.g. "2.50" for 2.5) is kept.
      written: parsed ? valueIdentity(parsed.value) : prev.written,
    }));
    if (parsed) onValue(parsed.value);
  };

  return (
    <div className="flow-conditional__value">
      <label className="flow-inspector__schema-field">
        <span>Value type</span>
        <select
          className="flow-inspector__select"
          data-testid="router-rule-type"
          value={type}
          onChange={(event) => {
            const nextType = event.target.value as ValueType;
            commit(nextType === "boolean" ? (draft === "false" ? "false" : "true") : draft, nextType);
          }}
        >
          {types.map((item) => (
            <option key={item} value={item}>
              {VALUE_TYPE_LABELS[item]}
              {allowed.length && !allowed.includes(item) ? " (not used by this comparison)" : ""}
            </option>
          ))}
        </select>
      </label>
      <label className="flow-inspector__schema-field">
        <span>Value</span>
        {type === "boolean" ? (
          <select className="flow-inspector__select" data-testid="router-rule-value" value={draft === "false" ? "false" : "true"} onChange={(event) => commit(event.target.value, type)}>
            <option value="true">Yes</option>
            <option value="false">No</option>
          </select>
        ) : type === "text_list" || type === "number_list" ? (
          <textarea className="flow-inspector__input" data-testid="router-rule-value" rows={3} value={draft} placeholder="One item per line" onChange={(event) => commit(event.target.value, type)} />
        ) : (
          <input
            className="flow-inspector__input"
            data-testid="router-rule-value"
            inputMode={type === "number" ? "decimal" : undefined}
            value={draft}
            onChange={(event) => commit(event.target.value, type)}
          />
        )}
      </label>
      {invalid ? (
        <div className="flow-conditional__note flow-conditional__note--attention" role="status">
          {type === "number" ? "Enter a number, for example 10 or 2.5." : "Enter one number per line."} The last valid value is kept until then.
        </div>
      ) : type === "text" && draft.trim() !== "" && Number.isFinite(Number(draft.trim())) ? (
        <div className="flow-conditional__note">Compared as text. Choose Number if the field holds a number.</div>
      ) : null}
    </div>
  );
}
