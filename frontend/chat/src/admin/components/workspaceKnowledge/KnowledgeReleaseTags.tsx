import { useState } from "react";
import { releaseCodeText } from "./jiraReleasesContract";
import { errorsFor, itemIndex, tagProblem } from "./jiraReleasesModel";
import type { FieldErrors, TagField } from "./jiraReleasesModel";

// Leading and trailing spaces are part of a literal prefix ("Release "): shown as ␣ so they can be seen.
function shown(value: string, literal: boolean): string {
  return literal ? value.replace(/^ +| +$/g, (spaces) => "␣".repeat(spaces.length)) : value;
}

export function FieldError({ path, code }: { path?: string; code: string }) {
  return (
    <div className="kr-field-error" role="alert" data-field={path}>
      <code>{code}</code> {releaseCodeText(code)}
    </div>
  );
}

// A chip list with free entry: Enter or Add appends a value, × removes one. Errors of the list or of one item
// (field[2]) are shown under it, and the refused item's chip is marked.
export function ReleaseTagList({ field, label, values, onChange, errors, placeholder, disabled }: {
  field: TagField;
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  errors: FieldErrors;
  placeholder: string;
  disabled?: boolean;
}) {
  const [entry, setEntry] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const literal = field === "releases.version_name_prefixes";
  const own = errorsFor(errors, field);
  const refused = new Set(own.map(([path]) => itemIndex(path, field)).filter((index): index is number => index !== null));

  const add = () => {
    const found = tagProblem(field, entry, values);
    setProblem(found);
    if (found) return;
    onChange([...values, literal ? entry : entry.trim()]);
    setEntry("");
  };

  return (
    <div className="admin-panel__stack admin-panel__stack--compact" data-field={field}>
      {values.length ? (
        <ul className="kr-chips" aria-label={label}>
          {values.map((value, index) => (
            <li key={`${index}-${value}`} className={`kr-chip${refused.has(index) ? " kr-chip--error" : ""}`}>
              <span>{shown(value, literal)}</span>
              {!disabled ? (
                <button type="button" className="kr-chip__remove" aria-label={`Remove ${value.trim() || "value"} from ${label}`}
                  onClick={() => onChange(values.filter((_, other) => other !== index))}>
                  ×
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {!disabled ? (
        <div className="kr-row">
          <input className={`admin-panel__form-input${problem ? " kr-input--error" : ""}`} aria-label={`Add to ${label}`}
            value={entry} placeholder={placeholder}
            onChange={(event) => { setEntry(event.target.value); setProblem(null); }}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                add();
              }
            }} />
          <button type="button" className="admin-panel__action-btn" onClick={add}>Add</button>
        </div>
      ) : null}
      {problem ? <FieldError code={problem} /> : null}
      {own.map(([path, code]) => <FieldError key={path} path={path} code={code} />)}
    </div>
  );
}
