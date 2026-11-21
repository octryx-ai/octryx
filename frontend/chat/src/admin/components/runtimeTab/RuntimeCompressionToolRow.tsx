import {
  coerceConfigValue,
  configLabel,
  strategyLabel,
  type ToolResultCompressor,
  type ToolResultCompressorDraft,
} from "./compressionModel";

type RuntimeCompressionToolRowProps = {
  item: ToolResultCompressor;
  draft: ToolResultCompressorDraft;
  saving: boolean;
  onDraftChange: (draft: ToolResultCompressorDraft) => void;
  onSave: () => void;
};

function ConfigInput({
  name,
  value,
  onChange,
}: {
  name: string;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const label = configLabel(name);
  if (typeof value === "boolean") {
    return (
      <label className="runtime-compression__limit">
        <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} />
        <span>{label}</span>
      </label>
    );
  }
  if (typeof value === "number" || typeof value === "string") {
    return (
      <label className="runtime-compression__limit">
        <span>{label}</span>
        <input
          className="admin-panel__input runtime-compression__limit-input"
          type={typeof value === "number" ? "number" : "text"}
          min={typeof value === "number" ? 0 : undefined}
          value={String(value)}
          onChange={(e) => onChange(coerceConfigValue(value, e.target.value))}
          aria-label={label}
        />
      </label>
    );
  }
  return (
    <span className="runtime-compression__limit">
      <span>{label}</span>
      <code>{JSON.stringify(value)}</code>
    </span>
  );
}

// One compressor as a compact table row: tool, profile, tunable limits, on/off, save.
export function RuntimeCompressionToolRow({
  item,
  draft,
  saving,
  onDraftChange,
  onSave,
}: RuntimeCompressionToolRowProps) {
  const configEntries = Object.entries(draft.config || {});
  return (
    <tr className={draft.is_active ? "" : "admin-panel__row--inactive"}>
      <td>
        <strong>{item.tool_name}</strong>
      </td>
      <td>
        {strategyLabel(draft.strategy)}
        <div className="admin-panel__cell--muted">
          <code>{draft.strategy}</code>
        </div>
      </td>
      <td>
        {configEntries.length === 0 ? (
          <span className="admin-panel__cell--muted">No tunable limits</span>
        ) : (
          <div className="runtime-compression__limits">
            {configEntries.map(([key, value]) => (
              <ConfigInput
                key={key}
                name={key}
                value={value}
                onChange={(next) =>
                  onDraftChange({ ...draft, config: { ...draft.config, [key]: next } })
                }
              />
            ))}
          </div>
        )}
      </td>
      <td>
        <label className="admin-toggle-row">
          <input
            type="checkbox"
            checked={draft.is_active}
            onChange={(e) => onDraftChange({ ...draft, is_active: e.target.checked })}
            aria-label={`Compress ${item.tool_name} results`}
          />
          <span>{draft.is_active ? "On" : "Off"}</span>
        </label>
      </td>
      <td>
        <button
          type="button"
          className="admin-panel__action-btn runtime-table__compact-btn"
          onClick={onSave}
          disabled={saving}
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </td>
    </tr>
  );
}
