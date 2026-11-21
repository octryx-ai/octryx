import { useEffect, useRef, useState } from "react";
import "./actionMenu.css";

export type ActionMenuItem = {
  label: string;
  onSelect: () => void;
  disabled?: boolean;
  // Toggle items (a panel that is open) show a check mark.
  checked?: boolean;
  danger?: boolean;
  testId?: string;
};

// Secondary actions of a page header grouped in one menu. Escape and an outside
// click close it; a danger item keeps its own confirm in `onSelect`.
// `row`: the "⋯" menu of a list row, named after its object ("More actions for jira-shop"); its list
// is positioned against the viewport so a table or card never clips it. Danger items come last.
export function ActionMenu({
  items,
  label = "More",
  buttonClassName = "admin-panel__action-btn",
  row,
}: {
  items: ActionMenuItem[];
  label?: string;
  buttonClassName?: string;
  row?: { objectName: string };
}) {
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<{ top: number; right: number } | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const ordered = row ? [...items.filter((item) => !item.danger), ...items.filter((item) => item.danger)] : items;

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("mousedown", onPointer);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onPointer);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="action-menu" ref={rootRef}>
      <button
        type="button"
        className={row ? "action-menu__row-btn" : buttonClassName}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={row ? `More actions for ${row.objectName}` : undefined}
        title={row ? `More actions for ${row.objectName}` : undefined}
        onClick={(event) => {
          if (row) {
            const rect = event.currentTarget.getBoundingClientRect();
            setAnchor({ top: rect.bottom + 4, right: Math.max(8, window.innerWidth - rect.right) });
          }
          setOpen((value) => !value);
        }}
      >
        {row ? "⋯" : `${label} ▾`}
      </button>
      {open ? (
        <div className={`action-menu__list${row ? " action-menu__list--row" : ""}`} role="menu"
          style={row && anchor ? { position: "fixed", top: anchor.top, right: anchor.right } : undefined}>
          {ordered.map((item) => (
            <button
              key={item.label}
              type="button"
              role={item.checked === undefined ? "menuitem" : "menuitemcheckbox"}
              aria-checked={item.checked}
              className={`action-menu__item${item.danger ? " action-menu__item--danger" : ""}`}
              disabled={item.disabled}
              data-testid={item.testId}
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
            >
              <span>{item.label}</span>
              {item.checked ? <span aria-hidden="true">✓</span> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
