import { useEffect, useRef, useState, type ReactNode } from "react";

import { MoreActionsIcon } from "../composerIcons";

export type WorkspaceHeaderMenuItem = {
  key: string;
  label: string;
  icon: ReactNode;
  onSelect: () => void;
  disabled?: boolean;
  active?: boolean;
};

// Progressive disclosure for the secondary workspace-header actions on phone
// widths. Trace access and the action-error control stay outside this
// menu on purpose: execution state must never need a menu to be seen.
// On desktop the same menu groups the two exports behind one labelled "Export" button (`trigger`).
export function WorkspaceHeaderOverflowMenu({
  items,
  children,
  trigger,
}: {
  items: WorkspaceHeaderMenuItem[];
  children?: ReactNode;
  trigger?: { label: string; ariaLabel: string; icon: ReactNode };
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node | null)) {
        setOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <div className="workspace__overflow stats-popover-shell" ref={containerRef}>
      <button
        type="button"
        className={`icon-action-button${trigger ? " icon-action-button--labeled" : ""}${open ? " icon-action-button--active" : ""}`}
        aria-label={trigger?.ariaLabel ?? "More chat actions"}
        title={trigger ? undefined : "More chat actions"}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        {trigger ? (
          <>
            {trigger.icon}
            <span>{trigger.label}</span>
          </>
        ) : (
          <MoreActionsIcon />
        )}
      </button>
      {open ? (
        <div className={`workspace__overflow-menu${trigger ? " workspace__overflow-menu--anchored" : ""}`} role="menu">
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              role="menuitem"
              className={`workspace__overflow-item ${item.active ? "workspace__overflow-item--active" : ""}`}
              disabled={item.disabled}
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
            >
              {item.icon}
              <span>{item.label}</span>
            </button>
          ))}
        </div>
      ) : null}
      {children}
    </div>
  );
}
