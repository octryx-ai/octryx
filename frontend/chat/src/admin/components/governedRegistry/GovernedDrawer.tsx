import { useEffect, type CSSProperties, type ReactNode } from "react";

// Right-side drawer of the governed admin editors (design guide §9.11): backdrop click and ESC
// close it; width by variant.
const WIDTHS = { edit: "28rem", gate: "32rem", detail: "38rem" } as const;

type Props = {
  title: string;
  eyebrow: string;
  variant: keyof typeof WIDTHS;
  onClose: () => void;
  footer?: ReactNode;
  children: ReactNode;
};

export function GovernedDrawer({ title, eyebrow, variant, onClose, footer, children }: Props) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="ws-drawer__backdrop" onClick={onClose}>
      <aside
        className="ws-drawer"
        style={{ "--ws-drawer-width": WIDTHS[variant] } as CSSProperties}
        role="dialog"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="ws-drawer__header">
          <div>
            <div className="ws-eyebrow">{eyebrow}</div>
            <div className="ws-bar__name">{title}</div>
          </div>
          <button type="button" className="ws-drawer__close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>
        <div className="ws-drawer__body">{children}</div>
        {footer ? <footer className="ws-drawer__footer">{footer}</footer> : null}
      </aside>
    </div>
  );
}

const STATE_BADGE: Record<string, string> = {
  draft: "inactive",
  in_review: "warning",
  published: "active",
  retired: "inactive",
};

export function RevisionStateBadge({ state }: { state: string }) {
  return <span className={`admin-panel__badge admin-panel__badge--${STATE_BADGE[state] ?? "inactive"}`}>{state.replace("_", " ")}</span>;
}
