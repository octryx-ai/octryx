// Inline multi-select of the user edit panel, used for a user's roles and groups.
import { useState } from "react";
import { CheckIcon, ChevronIcon } from "./userEditPanelParts";

/* ── Inline multi-select for roles and groups ────────────────── */

export function MultiSelect({
  options,
  selectedIds,
  onChange,
  noun,
}: {
  options: { id: string; name: string }[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  noun: { one: string; many: string };
}) {
  const [open, setOpen] = useState(false);

  const toggle = (id: string) => {
    onChange(
      selectedIds.includes(id)
        ? selectedIds.filter((x) => x !== id)
        : [...selectedIds, id],
    );
  };

  const label =
    selectedIds.length === 0
      ? `No ${noun.one} assigned`
      : selectedIds.length === 1
        ? (options.find((o) => o.id === selectedIds[0])?.name ??
          `1 ${noun.one}`)
        : `${selectedIds.length} ${noun.many} selected`;

  return (
    <div className="user-edit-panel__multi" style={{ position: "relative" }}>
      <button
        type="button"
        className="user-edit-panel__multi-trigger"
        onClick={() => setOpen((v) => !v)}
      >
        <span>{label}</span>
        <ChevronIcon />
      </button>
      {open && (
        <div className="user-edit-panel__multi-dropdown">
          {options.length === 0 ? (
            <span className="user-edit-panel__multi-empty">
              No {noun.many} available
            </span>
          ) : (
            options.map((g) => {
              const checked = selectedIds.includes(g.id);
              return (
                <button
                  key={g.id}
                  type="button"
                  className={`user-edit-panel__multi-option${checked ? " user-edit-panel__multi-option--on" : ""}`}
                  onClick={() => toggle(g.id)}
                >
                  <span className="user-edit-panel__multi-check">
                    {checked && <CheckIcon />}
                  </span>
                  {g.name}
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
