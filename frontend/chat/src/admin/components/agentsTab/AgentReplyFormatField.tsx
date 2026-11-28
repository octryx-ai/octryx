import type { ReplyFormatState } from "./agentReplyFields";
import { ReplyFormatFieldList, ReplyFormatModeChoices } from "./AgentReplyFormatParts";
import { useReplyFormatFieldState } from "./useReplyFormatFieldState";
import "./agentReplyFormat.css";

type AgentReplyFormatFieldProps = {
  value: ReplyFormatState;
  onChange: (value: ReplyFormatState) => void;
  /** Incremented by the form when a save is blocked by this field. */
  revealSignal?: number;
};

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
