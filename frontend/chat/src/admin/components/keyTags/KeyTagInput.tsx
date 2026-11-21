import { useState } from "react";
import { addKeys, removeKey } from "./keyTagsModel";
import type { KeyRule } from "./keyTagsModel";
import "./keyTags.css";

type Props = {
  id: string;
  // What one tag is, for labels and messages ("space", "project").
  noun: string;
  keys: string[];
  onChange: (keys: string[]) => void;
  rule?: KeyRule;
  placeholder?: string;
  // Keys to mark (e.g. configured but not visible to the account), with the reason shown on the tag.
  flagged?: Record<string, string>;
  disabled?: boolean;
  describedBy?: string;
};

// One key per tag: Enter, comma, space or a paste of several keys adds them; × or Backspace on an empty entry
// removes one. A key that does not match the rule stays in the entry with its reason instead of being saved.
export function KeyTagInput({ id, noun, keys, onChange, rule, placeholder, flagged = {}, disabled, describedBy }: Props) {
  const [entry, setEntry] = useState("");
  const [invalid, setInvalid] = useState<string[]>([]);

  const commit = (text: string) => {
    const result = addKeys(keys, text, rule);
    setInvalid(result.invalid);
    setEntry(result.invalid.join(" "));
    if (result.keys.length !== keys.length) onChange(result.keys);
  };

  return (
    <div className="key-tags" data-testid={`key-tags-${id}`}>
      <div className={`key-tags__box${invalid.length ? " key-tags__box--error" : ""}`}>
        {keys.map((key) => (
          <span key={key} className={`key-tags__tag${flagged[key] ? " key-tags__tag--flagged" : ""}`}
            title={flagged[key] || undefined} data-key={key}>
            {key}
            {!disabled ? (
              <button type="button" className="key-tags__remove" aria-label={`Remove ${noun} ${key}`}
                onClick={() => onChange(removeKey(keys, key))}>×</button>
            ) : null}
          </span>
        ))}
        {!disabled ? (
          <input id={id} className="key-tags__entry" value={entry} autoComplete="off" spellCheck={false}
            placeholder={keys.length ? "" : placeholder} aria-describedby={describedBy}
            aria-invalid={invalid.length > 0}
            onChange={(event) => {
              const text = event.target.value;
              setInvalid([]);
              if (/[\s,;]$/.test(text)) commit(text);
              else setEntry(text);
            }}
            onPaste={(event) => {
              const text = event.clipboardData.getData("text");
              if (/[\s,;]/.test(text.trim())) {
                event.preventDefault();
                commit(`${entry} ${text}`);
              }
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                commit(entry);
              } else if (event.key === "Backspace" && !entry && keys.length) {
                onChange(keys.slice(0, -1));
              }
            }}
            onBlur={() => { if (entry.trim()) commit(entry); }} />
        ) : null}
      </div>
      {invalid.length ? (
        <span className="security-field-hint security-field-hint--error" role="alert">
          Not a valid {noun} key: {invalid.join(", ")}
        </span>
      ) : null}
    </div>
  );
}
