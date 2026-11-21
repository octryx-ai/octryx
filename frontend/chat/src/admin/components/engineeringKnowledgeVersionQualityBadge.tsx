// Quality pill of an engineering knowledge pack version.
export function versionQualityBadge(qualityStatus: string) {
  const map: Record<string, { bg: string; color: string }> = {
    passed: { bg: "var(--status-active-soft)", color: "var(--status-active)" },
    failed: { bg: "var(--status-error-soft)", color: "var(--status-error)" },
    pending: { bg: "var(--status-attention-soft)", color: "var(--status-attention)" },
  };
  const s = map[qualityStatus] ?? {
    bg: "rgba(255,255,255,0.07)",
    color: "rgba(255,255,255,0.4)",
  };
  return (
    <span
      style={{
        background: s.bg,
        color: s.color,
        borderRadius: "var(--ds-radius-sm)",
        padding: "0.1rem 0.45rem",
        fontSize: "var(--ds-text-2xs)",
        fontWeight: 600,
      }}
    >
      {qualityStatus}
    </span>
  );
}
