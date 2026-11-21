import { DataTable } from "../../../layout/DataTable";
import { Field, type FieldErrors } from "./ConnectionFields";
import type { Pair, PairLabels } from "./connectionDraft";
import { humanize, scheduleOptions, scheduleText, type TicketState } from "./connectionTypes";

// Editors for a connection's uses: the schedule (the server's presets), a Knowledge scope as a
// plain list ("TEAM, OPS" — never raw JSON), and two-column mappings (status map, write-back transitions) whose rows
// can be added and removed. A refused save shows at its field (request path).

export function ScheduleSelect({ value, cron, path, errors, readOnly, onChange, onCronChange }: {
  value: string; cron: string; path: string; errors: FieldErrors; readOnly: boolean;
  onChange: (value: string) => void; onCronChange: (value: string) => void;
}) {
  const shown = value === "off" ? "manual" : value;
  const options = scheduleOptions(value);
  return (
    <>
      <Field label="Schedule" path={path} errors={errors}>
        <select className="admin-panel__input" value={shown} disabled={readOnly} onChange={(event) => onChange(event.target.value)}
          data-testid={`schedule-${path}`}>
          {shown ? null : <option value="">Choose…</option>}
          {options.map((option) => <option key={option} value={option}>{scheduleText(option)}</option>)}
        </select>
      </Field>
      {shown === "custom" ? (
        <Field label="Custom schedule" path={`${path}_cron`} errors={errors}>
          <input className="admin-panel__input" value={cron} disabled={readOnly} placeholder="*/30 * * * *"
            onChange={(event) => onCronChange(event.target.value)} data-testid={`schedule-cron-${path}`} />
          <span className="connections__fact">Five fields; at most every 15 minutes.</span>
        </Field>
      ) : null}
    </>
  );
}

export function ScopeEditor({ scopeKey, value, readOnly, errors, onChange }: {
  scopeKey: string; value: string; readOnly: boolean; errors: FieldErrors; onChange: (value: string) => void;
}) {
  const label = humanize(scopeKey);
  return (
    <Field label={`${label} to read`} path="uses.knowledge.scope" errors={errors}>
      <input className="admin-panel__input" value={value} disabled={readOnly} placeholder="e.g. DOCS, TEAM · empty: everything"
        onChange={(event) => onChange(event.target.value)} data-testid="connection-knowledge-scope" />
      <span className="connections__fact">Separate several with commas.</span>
    </Field>
  );
}

export function PairsEditor({ rows, labels, path, readOnly, errors, onChange, testId, states = [] }: {
  rows: Pair[]; labels: PairLabels; path: string; readOnly: boolean; errors: FieldErrors;
  onChange: (rows: Pair[]) => void; testId: string;
  // Our ticket states: when given, the "ours" column is a select of them (status_map[].ours must be one).
  states?: TicketState[];
}) {
  type Row = Pair & { index: number };
  const indexed: Row[] = rows.map((row, index) => ({ ...row, index }));
  const set = (index: number, key: keyof Pair, value: string) =>
    onChange(rows.map((row, at) => (at === index ? { ...row, [key]: value } : row)));
  const stateLabel = (key: string) => states.find((state) => state.key === key)?.label ?? key;
  const cell = (row: Row, key: keyof Pair, placeholder: string) => {
    if (key === "ours" && states.length) {
      if (readOnly) return stateLabel(row.ours);
      const known = states.some((state) => state.key === row.ours);
      return (
        <select className="admin-panel__input" value={row.ours} aria-label={`ours ${row.index + 1}`}
          onChange={(event) => set(row.index, "ours", event.target.value)} data-testid={`${testId}-ours-${row.index}`}>
          <option value="">{placeholder}</option>
          {row.ours && !known ? <option value={row.ours}>{row.ours} (unknown)</option> : null}
          {states.map((state) => <option key={state.key} value={state.key}>{state.label}</option>)}
        </select>
      );
    }
    return readOnly ? row[key] : (
      <input className="admin-panel__input" value={row[key]} placeholder={placeholder} aria-label={`${key} ${row.index + 1}`}
        onChange={(event) => set(row.index, key, event.target.value)} data-testid={`${testId}-${key}-${row.index}`} />
    );
  };
  // A refusal for the table ("uses.tickets.status_map") or one row ("…status_map[2]…" / "…status_map.2…").
  const rowMatch = errors ? new RegExp(`^${path.replace(/\./g, "\\.")}(?:\\[(\\d+)\\]|\\.(\\d+))`).exec(errors.field) : null;
  const errorRow = rowMatch ? Number(rowMatch[1] ?? rowMatch[2]) : null;
  const error = errors && (errors.field === path || rowMatch) ? errors.message : "";
  return (
    <div className="connections__pairs" data-field={path}>
      <DataTable<Row>
        label={labels.title} testId={testId} rows={indexed} rowKey={(row) => String(row.index)}
        empty={{ text: labels.empty }}
        columns={[
          { key: "left", header: labels.left, grow: true, render: (row) => cell(row, labels.leftKey, labels.leftPlaceholder) },
          { key: "right", header: labels.right, grow: true, render: (row) => cell(row, labels.rightKey, labels.rightPlaceholder) },
          ...(readOnly ? [] : [{ key: "remove", header: "", nowrap: true, align: "end" as const, render: (row: Row) => (
            <button type="button" className="admin-panel__action-btn" aria-label={`Remove row ${row.index + 1}`}
              onClick={() => onChange(rows.filter((_, at) => at !== row.index))} data-testid={`${testId}-remove-${row.index}`}>Remove</button>
          ) }]),
        ]}
      />
      {readOnly ? null : (
        <button type="button" className="admin-panel__action-btn" onClick={() => onChange([...rows, { source: "", ours: "" }])}
          data-testid={`${testId}-add`}>Add row</button>
      )}
      {error ? (
        <span className="connections__field-error" role="alert" data-testid={`field-error-${path}`}>
          {errorRow !== null ? `Row ${errorRow + 1}: ` : ""}{error}
        </span>
      ) : null}
    </div>
  );
}
