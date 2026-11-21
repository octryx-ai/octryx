import { useEffect, useMemo, useState } from "react";

import type { AdminIdentityGroupRow } from "./identityTypes";

type RlsAttribute = { key: string; value: string };

type AdminIdentityGroupRlsEditorProps = {
  group: AdminIdentityGroupRow;
  loading: boolean;
  onSave: (attributes: RlsAttribute[]) => void;
};

function normalizeRows(attributes: RlsAttribute[]): RlsAttribute[] {
  return attributes.length > 0 ? attributes : [{ key: "", value: "" }];
}

export function AdminIdentityGroupRlsEditor({
  group,
  loading,
  onSave,
}: AdminIdentityGroupRlsEditorProps) {
  const initialRows = useMemo(
    () => normalizeRows(group.rls_attributes || []),
    [group.rls_attributes],
  );
  const [rows, setRows] = useState<RlsAttribute[]>(initialRows);
  useEffect(() => {
    setRows(initialRows);
  }, [initialRows]);

  const setRowField = (
    index: number,
    field: keyof RlsAttribute,
    value: string,
  ) => {
    setRows((current) =>
      current.map((row, rowIndex) =>
        rowIndex === index ? { ...row, [field]: value } : row,
      ),
    );
  };
  const removeRow = (index: number) => {
    setRows((current) =>
      normalizeRows(current.filter((_, rowIndex) => rowIndex !== index)),
    );
  };
  const cleanedRows = rows
    .map((row) => ({ key: row.key.trim(), value: row.value.trim() }))
    .filter((row) => row.key || row.value);
  const summary = group.rls_attributes?.length
    ? group.rls_attributes
        .map((attribute) => `${attribute.key}=${attribute.value}`)
        .join(", ")
    : "No data access attributes";

  return (
    <details className="admin-users__rls-editor">
      <summary>{summary}</summary>
      <div className="admin-users__rls-rows">
        {rows.map((row, index) => (
          <RlsRow key={`${group.id}:${index}`} row={row} index={index} groupName={group.name}
            removable={!(rows.length === 1 && !row.key && !row.value)} setRowField={setRowField} removeRow={removeRow} />
        ))}
      </div>
      <RlsEditorActions loading={loading} onAdd={() =>
        setRows((current) => [...current, { key: "", value: "" }])
      } onSave={() => onSave(cleanedRows)} />
      <p className="admin-panel__hint">
        Managed database row-level security (RLS) rules can reference these as <code>$group.rls.tenantid</code> to limit which rows members see.
      </p>
    </details>
  );
}

// One attribute: its key and value inputs and Remove (off while it is the only, empty row).
function RlsRow({ row, index, groupName, removable, setRowField, removeRow }: {
  row: RlsAttribute;
  index: number;
  groupName: string;
  removable: boolean;
  setRowField: (index: number, field: keyof RlsAttribute, value: string) => void;
  removeRow: (index: number) => void;
}) {
  return (
    <div className="admin-users__rls-row">
      <input
        className="connector-field__input"
        value={row.key}
        onChange={(event) =>
          setRowField(index, "key", event.target.value)
        }
        placeholder="tenantid"
        aria-label={`Data access attribute key ${index + 1} for ${groupName}`}
      />
      <input
        className="connector-field__input"
        value={row.value}
        onChange={(event) =>
          setRowField(index, "value", event.target.value)
        }
        placeholder="11"
        aria-label={`Data access attribute value ${index + 1} for ${groupName}`}
      />
      <button
        type="button"
        className="admin-users__table-action"
        onClick={() => removeRow(index)}
        disabled={!removable}
      >
        Remove
      </button>
    </div>
  );
}

function RlsEditorActions({ loading, onAdd, onSave }: { loading: boolean; onAdd: () => void; onSave: () => void }) {
  return (
    <div className="admin-inline-actions">
      <button
        type="button"
        className="admin-panel__action-btn"
        onClick={onAdd}
      >
        Add attribute
      </button>
      <button
        type="button"
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        onClick={onSave}
        disabled={loading}
      >
        {loading ? "Saving..." : "Save attributes"}
      </button>
    </div>
  );
}
