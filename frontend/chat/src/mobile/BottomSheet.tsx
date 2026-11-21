// The phone's one overlay: a sheet from the bottom (in thumb reach) over a dimmed page. Tapping outside, the close
// button or Escape closes it; the page behind does not scroll while it is open. Rendered into the body: a header with a
// backdrop filter would otherwise hold the fixed layer inside itself.

import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Icon } from "./icons";

export function BottomSheet({
  title,
  onClose,
  children,
  footer,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const panel = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panel.current?.focus();
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);
  return createPortal(
    <div className="m-sheet-layer">
      <button type="button" className="m-sheet-backdrop" aria-label="Close" tabIndex={-1} onClick={onClose} />
      <div ref={panel} className="m-sheet-panel" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}>
        <div className="m-sheet-grip" aria-hidden="true" />
        <header className="m-sheet-head">
          <h2>{title}</h2>
          <button type="button" className="m-icon-button" aria-label="Close" onClick={onClose}>
            <Icon name="close" size={20} />
          </button>
        </header>
        <div className="m-sheet-body">{children}</div>
        {footer && <footer className="m-sheet-foot">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}
