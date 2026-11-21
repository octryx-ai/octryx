// The quiet audit mark: a small lock instead of "POLICIES ENFORCED · ALL RUNS AUDITED" in capitals; the
// sentence is the tooltip. It sits in the chat header's context line, next to the runtime.
export const AUDIT_MARK_TITLE = "Policies are enforced and every run is audited.";

export function AuditMark() {
  return (
    <span className="composer__audit-mark" title={AUDIT_MARK_TITLE} data-testid="chat-audit-mark">
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <rect x="4.5" y="9" width="11" height="8" rx="1.6" />
        <path d="M7 9V6.5a3 3 0 0 1 6 0V9" />
      </svg>
      <span>Audited</span>
    </span>
  );
}
