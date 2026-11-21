import type { ReactNode } from "react";

// Stroke icons for palette entries, keyed by catalog icon hint or node type.
function StrokeIcon({ children, size = 14 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

const trigger = <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />;
const join = (
  <>
    <path d="M12 3v10M6 15l6 4 6-4" />
    <path d="M6 9l6 4 6-4" opacity="0.5" />
  </>
);
const agent = (
  <>
    <path d="M12 3l7 4v10l-7 4-7-4V7l7-4z" />
    <path d="M8.5 10.5l3.5 2 3.5-2" />
    <path d="M12 12.5v4" />
  </>
);
const tool = (
  <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
);

const ICON_PATHS: Record<string, ReactNode> = {
  trigger,
  router: (
    <>
      <path d="M16 3h5v5M8 3H3v5M3 16v5h5M21 16v5h-5" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  parallel: (
    <>
      <path d="M8 6h8M8 12h8M8 18h8" />
      <circle cx="4" cy="6" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="4" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="4" cy="18" r="1.5" fill="currentColor" stroke="none" />
    </>
  ),
  join,
  subflow: join,
  agent_step: agent,
  tool_step: tool,
  retrieval: (
    <>
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.35-4.35" />
    </>
  ),
  policy_gate: (
    <>
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </>
  ),
  clarification_gate: (
    <>
      <circle cx="12" cy="12" r="10" />
      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
      <path d="M12 17h.01" />
    </>
  ),
  approval: (
    <>
      <path d="M12 3 4 7v6c0 5 3.4 8.3 8 9 4.6-.7 8-4 8-9V7l-8-4Z" />
      <path d="M9 12l2 2 4-4" />
    </>
  ),
  evaluation: (
    <>
      <line x1="18" y1="20" x2="18" y2="10" />
      <line x1="12" y1="20" x2="12" y2="4" />
      <line x1="6" y1="20" x2="6" y2="14" />
    </>
  ),
  output: (
    <>
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </>
  ),
  supervisor: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
      <circle cx="4" cy="8" r="2" />
      <path d="M4 6v4" />
      <circle cx="20" cy="8" r="2" />
      <path d="M20 6v4" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </>
  ),
  plus: (
    <>
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </>
  ),
  close: (
    <>
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </>
  ),
};

export function PaletteIcon({ hint, fallback, size }: { hint: string; fallback?: string; size?: number }) {
  return <StrokeIcon size={size}>{ICON_PATHS[hint] ?? (fallback ? ICON_PATHS[fallback] : undefined) ?? tool}</StrokeIcon>;
}
