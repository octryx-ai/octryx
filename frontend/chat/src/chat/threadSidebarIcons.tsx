// Icons of the chat sidebar (WP chat sidebar redesign); paths match the approved mock.

export function ThreadFolderIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M2.75 6.75h4.1l1.4 1.5h9v6.75H2.75z" />
      <path d="M2.75 6.75V5.5h4.6l1.05 1.25" />
    </svg>
  );
}

export function ThreadChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      className={`thread-card__chevron ${open ? "thread-card__chevron--open" : ""}`}
      viewBox="0 0 20 20"
      aria-hidden="true"
    >
      <path d="M7.25 5.5 12 10l-4.75 4.5" />
    </svg>
  );
}

export function ThreadMoreIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <circle cx="5" cy="10" r="1.4" />
      <circle cx="10" cy="10" r="1.4" />
      <circle cx="15" cy="10" r="1.4" />
    </svg>
  );
}

export function SelectChatsIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <rect x="3" y="3" width="6" height="6" rx="1.4" />
      <path d="M4.6 6.1l1 1 1.8-2" />
      <path d="M12 6h5M12 14h5" />
      <rect x="3" y="11" width="6" height="6" rx="1.4" />
    </svg>
  );
}

export function CloseIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M5.5 5.5l9 9M14.5 5.5l-9 9" />
    </svg>
  );
}

export function UndoIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M7 5 3.5 8.5 7 12" />
      <path d="M4 8.5h8a4 4 0 0 1 0 8H9" />
    </svg>
  );
}

export function WarnIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M10 3 2.5 16.5h15z" />
      <path d="M10 8v4M10 14.2v.1" />
    </svg>
  );
}

export function InfoIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <circle cx="10" cy="10" r="7" />
      <path d="M10 9v4.5M10 6.6v.1" />
    </svg>
  );
}

/** The visible box of a selection checkbox: a check glyph, or a dash when indeterminate. */
export function ThreadCheckboxBox() {
  return (
    <span aria-hidden="true">
      <svg viewBox="0 0 20 20" className="thread-card__checkbox-check">
        <path d="M4.5 10.5 8 14l7.5-8" />
      </svg>
      <svg viewBox="0 0 20 20" className="thread-card__checkbox-dash">
        <path d="M5 10h10" />
      </svg>
    </span>
  );
}

export function LaptopIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <rect x="4" y="4.5" width="12" height="8" rx="1" />
      <path d="M2.5 15.5h15" />
    </svg>
  );
}
