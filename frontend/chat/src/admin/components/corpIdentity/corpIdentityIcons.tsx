// Inline SVG icons for Settings -> Organization -> Corporate identity.
import type { OfficeTemplateType } from "../../types/adminPanelTypes.runtimeCorp";

export function DocTypeIcon({ type }: { type: OfficeTemplateType }) {
  if (type === "pptx") {
    return (
      <svg
        viewBox="0 0 20 20"
        aria-hidden="true"
        width="13"
        height="13"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <rect x="2" y="2" width="16" height="16" rx="2" />
        <path d="M6 7h8M6 10h5M6 13h7" />
      </svg>
    );
  }
  if (type === "docx") {
    return (
      <svg
        viewBox="0 0 20 20"
        aria-hidden="true"
        width="13"
        height="13"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M13 2H5v16h8V2Z" />
        <path d="M13 2v6h6" />
        <path d="M7 9h6M7 12h4" />
      </svg>
    );
  }
  return (
    <svg
      viewBox="0 0 20 20"
      aria-hidden="true"
      width="13"
      height="13"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="2" y="2" width="16" height="16" rx="2" />
      <path d="M6 10h8M6 13h8M6 7h3" />
    </svg>
  );
}

export function EditIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      aria-hidden="true"
      width="14"
      height="14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4 13.75V16h2.25L14.9 7.35l-2.25-2.25L4 13.75Z" />
    </svg>
  );
}

export function RefreshIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      aria-hidden="true"
      width="13"
      height="13"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M6.25 5.25V9H10" />
      <path d="M6.45 9a4.75 4.75 0 1 0 1.1-3.2" />
    </svg>
  );
}

export function UploadIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      aria-hidden="true"
      width="13"
      height="13"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M10 14V4M6 8l4-4 4 4" />
      <path d="M3 14v1a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-1" />
    </svg>
  );
}

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
