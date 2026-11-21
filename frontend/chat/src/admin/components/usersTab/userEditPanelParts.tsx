// Shared presentational parts of the user edit panel: close, check and chevron icons and the section label.
import type { ReactNode } from "react";

export function CloseIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      aria-hidden="true"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
    >
      <path d="M5 5 15 15M15 5 5 15" />
    </svg>
  );
}

export function CheckIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      aria-hidden="true"
      width="11"
      height="11"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4.5 10.5 8.5 14.5 15.5 6" />
    </svg>
  );
}

export function ChevronIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      aria-hidden="true"
      width="11"
      height="11"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
    >
      <path d="M5 7.5 10 12.5 15 7.5" />
    </svg>
  );
}

/* ── Section header ─────────────────────────────────────────── */

export function SectionLabel({ children }: { children: ReactNode }) {
  return <p className="user-edit-panel__section-label">{children}</p>;
}
