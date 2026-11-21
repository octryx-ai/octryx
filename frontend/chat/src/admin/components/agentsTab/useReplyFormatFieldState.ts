// The reply format field's state: which problems show, the reveal on a blocked save, and the edits.
import { useEffect, useId, useRef, useState } from "react";

import { MAX_REPLY_FIELDS, newReplyField, type ReplyField, type ReplyFormatState } from "./agentReplyFields";
import { replyFieldIssues, replyFieldsError } from "./agentReplyFormat";

export function useReplyFormatFieldState(
  value: ReplyFormatState,
  onChange: (value: ReplyFormatState) => void,
  revealSignal: number,
) {
  const name = useId();
  const [touched, setTouched] = useState<ReadonlySet<string>>(() => new Set());
  const [interacted, setInteracted] = useState(false);
  const [revealAll, setRevealAll] = useState(false);
  const seenSignal = useRef(revealSignal);
  const nameInputs = useRef(new Map<string, HTMLInputElement>());
  const addButton = useRef<HTMLButtonElement | null>(null);
  const issues =
    value.mode === "json_object" ? replyFieldIssues(value.fields) : null;

  useEffect(() => {
    if (revealSignal === seenSignal.current) return;
    seenSignal.current = revealSignal;
    setRevealAll(true);
    const target = issues?.firstKey
      ? nameInputs.current.get(issues.firstKey)
      : addButton.current;
    target?.scrollIntoView?.({ block: "center" });
    target?.focus?.();
    // Only a new blocked save reveals and focuses; editing afterwards does not move the focus.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revealSignal]);

  const setFields = (fields: ReplyField[]) => onChange({ ...value, fields });
  const rowIssue = (key: string) =>
    issues && (revealAll || touched.has(key))
      ? (issues.rows[key] ?? null)
      : null;
  return {
    name, nameInputs, addButton, setFields, rowIssue, setTouched, setInteracted,
    updateField: (key: string, patch: Partial<ReplyField>) =>
      setFields(value.fields.map((field) => (field.key === key ? { ...field, ...patch } : field))),
    chooseStructured: () =>
      onChange({ ...value, mode: "json_object", fields: value.fields.length ? value.fields : [newReplyField()] }),
    generalIssue: issues && (revealAll || interacted) ? issues.general : null,
    full: value.fields.length >= MAX_REPLY_FIELDS,
    valid: value.mode === "json_object" && !replyFieldsError(value.fields),
  };
}

export type ReplyFormatFieldState = ReturnType<typeof useReplyFormatFieldState>;
