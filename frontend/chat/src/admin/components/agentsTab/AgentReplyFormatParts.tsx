// Parts of the reply format field: the mode choice and the rows of the structured fields.
import { FIELD_TYPE_OPTIONS, MAX_REPLY_FIELDS, fieldTypeFromValue, fieldTypeValue, newReplyField, type ReplyField, type ReplyFormatState } from "./agentReplyFields";
import { replyFormatPreview } from "./agentReplyFormat";
import type { ReplyFormatFieldState } from "./useReplyFormatFieldState";

type PartProps = {
  value: ReplyFormatState;
  onChange: (value: ReplyFormatState) => void;
  state: ReplyFormatFieldState;
};

export function ReplyFormatModeChoices({ value, onChange, state }: PartProps) {
  const { name, chooseStructured } = state;
  return (
    <>
      <label className="agents-form__check">
        <input
          type="radio"
          name={name}
          value="text"
          checked={value.mode === "text"}
          onChange={() => onChange({ ...value, mode: "text" })}
        />
        <span>
          Free text
          <span className="agents-form__help">
            The agent answers in its own words. Replies are not checked. This is
            the default.
          </span>
        </span>
      </label>
      <label className="agents-form__check">
        <input
          type="radio"
          name={name}
          value="json_object"
          checked={value.mode === "json_object"}
          onChange={chooseStructured}
        />
        <span>
          Structured data (JSON, checked)
          <span className="agents-form__help">
            The agent must reply with one JSON object containing the fields
            below. A reply that does not match is not accepted as a successful
            result.
          </span>
        </span>
      </label>
      {value.mode === "unsupported" ? (
        <ReplyFormatInvalidNotice value={value} onChange={onChange} state={state} />
      ) : null}
    </>
  );
}

function ReplyFormatInvalidNotice({ value, onChange, state }: PartProps) {
  const { chooseStructured } = state;
  return (
    <div
      className="admin-panel__form-error agent-reply-format__invalid"
      role="status"
      data-testid="agent-reply-format-invalid"
    >
      <span>
        This agent&apos;s saved output format is not valid, so neither
        option is selected. The server refuses to save the agent until a
        valid format is chosen. Choose Free text, or define the fields again
        as Structured data. Nothing is replaced for you.
      </span>
      <span className="agent-reply-format__invalid-actions">
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={() => onChange({ ...value, mode: "text" })}
        >
          Use free text
        </button>
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={chooseStructured}
        >
          Define fields again
        </button>
      </span>
    </div>
  );
}

export function ReplyFormatFieldList({ value, state }: Omit<PartProps, "onChange">) {
  return (
    <div
      className="agent-reply-format"
      data-testid="agent-reply-format-fields"
      role="group"
      aria-label="Fields of the structured reply"
    >
      {value.fields.length ? (
        <div
          className="agent-reply-format__grid agent-reply-format__head"
          aria-hidden="true"
        >
          <span className="admin-panel__form-label">Field name</span>
          <span className="admin-panel__form-label">Type</span>
          <span className="admin-panel__form-label">Required</span>
          <span />
        </div>
      ) : null}
      {value.fields.map((field, index) => (
        <ReplyFieldRow key={field.key} value={value} state={state} field={field} index={index} />
      ))}
      <ReplyFormatListFooter value={value} state={state} />
    </div>
  );
}

function ReplyFieldRow({
  value,
  state,
  field,
  index,
}: Omit<PartProps, "onChange"> & { field: ReplyField; index: number }) {
  const issue = state.rowIssue(field.key);
  const issueId = `${state.name}-issue-${field.key}`;
  return (
    <div className="agent-reply-format__item">
      <div className="agent-reply-format__grid">
        <ReplyFieldNameInput state={state} field={field} index={index} issue={issue} issueId={issueId} />
        <ReplyFieldTypeAndRemove value={value} state={state} field={field} index={index} />
      </div>
      {issue ? (
        <div
          id={issueId}
          className="admin-panel__form-error"
          role="status"
          data-testid="agent-reply-format-row-error"
        >
          {issue}
        </div>
      ) : null}
    </div>
  );
}

function ReplyFieldNameInput({
  state,
  field,
  index,
  issue,
  issueId,
}: Pick<PartProps, "state"> & { field: ReplyField; index: number; issue: string | null; issueId: string }) {
  const { nameInputs, updateField, setTouched } = state;
  return (
    <input
      ref={(element) => {
        if (element) nameInputs.current.set(field.key, element);
        else nameInputs.current.delete(field.key);
      }}
      className="connector-field__input"
      aria-label={`Field ${index + 1} name`}
      aria-invalid={issue ? true : undefined}
      aria-describedby={issue ? issueId : undefined}
      data-reply-field-key={field.key}
      placeholder="field_name"
      value={field.name}
      onChange={(event) =>
        updateField(field.key, { name: event.target.value })
      }
      onBlur={() =>
        setTouched((previous) => new Set(previous).add(field.key))
      }
    />
  );
}

function ReplyFieldTypeAndRemove({
  value,
  state,
  field,
  index,
}: Omit<PartProps, "onChange"> & { field: ReplyField; index: number }) {
  const { updateField, setInteracted, setFields } = state;
  return (
    <>
      <select
        className="connector-field__input"
        aria-label={`Field ${index + 1} type`}
        value={fieldTypeValue(field)}
        onChange={(event) =>
          updateField(
            field.key,
            fieldTypeFromValue(event.target.value),
          )
        }
      >
        {FIELD_TYPE_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <input
        type="checkbox"
        className="agent-reply-format__required"
        aria-label={`Field ${index + 1} required`}
        checked={field.required}
        onChange={(event) =>
          updateField(field.key, { required: event.target.checked })
        }
      />
      <button
        type="button"
        className="admin-panel__icon-btn"
        aria-label={`Remove field ${index + 1}`}
        title="Remove field"
        onClick={() => {
          setInteracted(true);
          setFields(
            value.fields.filter((item) => item.key !== field.key),
          );
        }}
      >
        ✕
      </button>
    </>
  );
}

function ReplyFormatListFooter({ value, state }: Omit<PartProps, "onChange">) {
  const { addButton, full, generalIssue, valid, setInteracted, setFields } = state;
  return (
    <>
      <div className="agent-reply-format__add">
        <button
          ref={addButton}
          type="button"
          className="admin-panel__action-btn"
          disabled={full}
          onClick={() => {
            setInteracted(true);
            setFields([...value.fields, newReplyField()]);
          }}
        >
          + Add field
        </button>
        {full ? (
          <span
            className="agents-form__help"
            data-testid="agent-reply-format-full"
          >
            At most {MAX_REPLY_FIELDS} fields.
          </span>
        ) : null}
      </div>
      {generalIssue ? (
        <div
          className="admin-panel__form-error"
          role="status"
          data-testid="agent-reply-format-error"
        >
          {generalIssue}
        </div>
      ) : null}
      {valid ? (
        <div>
          <span className="agents-form__help">
            Example of a valid reply
          </span>
          <pre
            className="agent-reply-format__preview"
            data-testid="agent-reply-format-preview"
          >
            {replyFormatPreview(value.fields)}
          </pre>
        </div>
      ) : null}
    </>
  );
}
