import type { ReplyFormatState } from "./agentReplyFields";
import { ReplyFormatFieldList, ReplyFormatModeChoices } from "./AgentReplyFormatParts";
import { useReplyFormatFieldState } from "./useReplyFormatFieldState";
import "./agentReplyFormat.css";

type AgentReplyFormatFieldProps = {
  value: ReplyFormatState;
  onChange: (value: ReplyFormatState) => void;
  /**
   * Incremented by the form when a save is blocked by this field. Every problem is then shown,
   * and the first problem's control is scrolled into view and focused.
   */
  revealSignal?: number;
};

// Output format: free text (default) or structured data whose replies are checked against the
// declared fields. Fields are chosen from a short list; no raw schema editing. Switching between the
// two keeps the fields for this edit. A saved format the server cannot accept is never replaced
// silently. one row per field under column headers; a field's problem shows once the author
// has left that field, or after a blocked save, never before they interacted.
export function AgentReplyFormatField({
  value,
  onChange,
  revealSignal = 0,
}: AgentReplyFormatFieldProps) {
  const state = useReplyFormatFieldState(value, onChange, revealSignal);

  return (
    <fieldset className="agents-form__field agents-form__choices">
      <legend className="admin-panel__form-label">Output format</legend>
      <ReplyFormatModeChoices value={value} onChange={onChange} state={state} />
      {value.mode === "json_object" ? (
        <ReplyFormatFieldList value={value} state={state} />
      ) : null}
    </fieldset>
  );
}
