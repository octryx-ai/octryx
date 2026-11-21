import "../work/workItemsLean.css";

// "Run on": where a workflow run executes. One select for every place that starts a run (Work item › Start a
// workflow run, the chat's start card); the options and their default come from the server, the sentence for the
// chosen option stands below the select so its label is never cut.
export function RunOnSelect({
  id,
  options,
  value,
  onChange,
  help,
  disabled = false,
}: {
  id: string;
  options: readonly { key: string; label: string }[];
  value: string;
  onChange: (key: string) => void;
  help?: string | null;
  disabled?: boolean;
}) {
  if (!options.length) return null;
  const chosen = options.find((option) => option.key === value);
  return (
    <div className="admin-panel__field">
      <label htmlFor={id}>Run on</label>
      <select
        id={id}
        className="admin-panel__input work-run-start__target"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        title={chosen?.label}
      >
        {options.map((option) => (
          <option key={option.key} value={option.key}>
            {option.label}
          </option>
        ))}
      </select>
      {help ? (
        <p className="work-run-start__hint" data-testid="work-run-target-help">
          {help}
        </p>
      ) : null}
    </div>
  );
}
