import type { MappingRow } from "./identityMappingRows";
import { mappingProblems } from "./identityMappingRows";

// One mapping list of an identity provider: the external group name typed as the provider sends it, the local roles
// or groups picked by name (never typed ids).
export function GroupMappingEditor({ title, rows, options, onChange, testId }: {
  title: string;
  rows: MappingRow[];
  options: { value: string; label: string }[];
  onChange: (rows: MappingRow[]) => void;
  testId: string;
}) {
  const update = (index: number, next: MappingRow) => onChange(rows.map((row, at) => (at === index ? next : row)));
  const problems = mappingProblems(rows);
  return (
    <div className="admin-users__mapping-editor" data-testid={testId}>
      <strong>{title}</strong>
      {rows.length === 0 ? <p className="admin-panel__hint">No mapping.</p> : null}
      {rows.map((row, index) => (
        <div key={index} className="admin-users__mapping-row">
          <label className="admin-panel__field">
            <span>External group</span>
            <input value={row.external} aria-label={`${title}: external group ${index + 1}`}
              onChange={(event) => update(index, { ...row, external: event.target.value })} />
          </label>
          <div className="admin-users__provider-checks">
            {options.map((option) => (
              <label key={option.value} className="admin-panel__checkbox">
                <input type="checkbox" checked={row.targets.includes(option.value)}
                  onChange={(event) => update(index, {
                    ...row,
                    targets: event.target.checked
                      ? [...row.targets, option.value]
                      : row.targets.filter((target) => target !== option.value),
                  })} />
                {option.label}
              </label>
            ))}
            {options.length === 0 ? <span className="admin-panel__hint">Nothing to map to yet.</span> : null}
          </div>
          <button type="button" className="admin-panel__action-btn" onClick={() => onChange(rows.filter((_, at) => at !== index))}>
            Remove
          </button>
        </div>
      ))}
      <div>
        <button type="button" className="admin-panel__action-btn" onClick={() => onChange([...rows, { external: "", targets: [] }])}>
          Add mapping
        </button>
      </div>
      {problems.length ? <ul className="admin-panel__error">{problems.map((line) => <li key={line}>{line}</li>)}</ul> : null}
    </div>
  );
}
