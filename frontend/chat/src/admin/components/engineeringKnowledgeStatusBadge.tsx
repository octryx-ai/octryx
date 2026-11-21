// Status pill shared by the Engineering Knowledge Pack admin views.
export function statusBadge(status: string) {
  const activeMap: Record<string, string> = {
    published: "var(--status-active)",
    passed: "var(--status-active)",
    active: "var(--status-active)",
    draft: "var(--status-attention)",
    draft_created: "var(--status-attention)",
    pending: "var(--status-attention)",
    pending_review: "var(--status-attention)",
  };
  const inactiveMap: Record<string, string> = {
    blocked: "var(--status-error)",
    failed: "var(--status-error)",
    rejected: "var(--status-error)",
    inactive: "rgba(255,255,255,0.2)",
  };
  const color =
    activeMap[status] ?? inactiveMap[status] ?? "rgba(255,255,255,0.3)";
  return (
    <span
      style={{
        background: `${color}22`,
        color,
        borderRadius: "var(--ds-radius-sm)",
        padding: "0.1rem 0.45rem",
        fontSize: "var(--ds-text-2xs)",
        fontWeight: 600,
      }}
    >
      {status}
    </span>
  );
}
