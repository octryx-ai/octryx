export function SearchIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <circle cx="9" cy="9" r="5.5" />
      <path d="M13.5 13.5 17 17" />
    </svg>
  );
}

export function RefreshIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M15.5 7.25V3.5h-3.75" />
      <path d="M4.8 6.2A6.5 6.5 0 0 1 15.5 7.25" />
      <path d="M4.5 12.75v3.75h3.75" />
      <path d="M15.2 13.8A6.5 6.5 0 0 1 4.5 12.75" />
    </svg>
  );
}

export function FolderPlusIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M2.75 6.75h4.1l1.4 1.5h9v6.75H2.75z" />
      <path d="M13.25 3.75v4M11.25 5.75h4" />
    </svg>
  );
}

export function FolderIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M2.75 6.75h4.35l1.2 1.5h8.95v6.5H2.75z" />
      <path d="M2.75 6.75V5.25h4.9l1.1 1.5" />
    </svg>
  );
}

export function FileIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M5.25 2.75h6.5l3 3v10.5H5.25z" />
      <path d="M11.75 2.75v3h3" />
    </svg>
  );
}

export function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      viewBox="0 0 20 20"
      aria-hidden="true"
      className={open ? "workspace-sidepanel__chevron--open" : ""}
    >
      <path d="M7 5.75 12.25 10 7 14.25" />
    </svg>
  );
}

export function TrashIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M5.75 6.25h8.5l-.6 9.25H6.35z" />
      <path d="M7.75 6.25V4.5h4.5v1.75" />
      <path d="M4.5 6.25h11" />
    </svg>
  );
}

export function RenameIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M4 14.5 13.5 5l2.5 2.5L6.5 17H4z" />
      <path d="m12.75 5.75 2.5 2.5" />
    </svg>
  );
}

export function MoveIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M10 3.5v13" />
      <path d="M6.75 6.75 10 3.5l3.25 3.25" />
      <path d="m6.75 13.25 3.25 3.25 3.25-3.25" />
    </svg>
  );
}

export function CleanIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M5 14.5c1.2 1.3 2.9 2 5 2 3.3 0 5.5-2.2 5.5-5.2S13.3 6 10 6" />
      <path d="M6.25 8.25 4.5 6.5l1.75-1.75" />
      <path d="M4.5 6.5H10" />
    </svg>
  );
}
