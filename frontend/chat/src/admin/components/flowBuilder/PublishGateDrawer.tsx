import type { FlowValidationReport } from "./flowBuilderTypes";

type ReadinessBadge = {
  key: string;
  label: string;
  status: "ok" | "warning" | "error";
};

const BADGE_LABELS: Record<string, string> = {
  security: "Security",
  privacy: "Privacy",
  cost: "Cost",
  reliability: "Reliability",
  observability: "Observability",
  eval: "Eval",
  rollback: "Rollback",
};

type PublishGateDrawerProps = {
  report: FlowValidationReport;
  onClose: () => void;
  onPublish: () => void;
  onPublishToStaging?: () => void;
  busy: boolean;
};

type GateIssue = FlowValidationReport["errors"][number];

function readinessBadges(report: FlowValidationReport): ReadinessBadge[] {
  return [
    { key: "security", label: "Security", status: "ok" },
    { key: "privacy", label: "Privacy", status: "ok" },
    { key: "cost", label: "Cost", status: "ok" },
    {
      key: "reliability",
      label: "Reliability",
      status: report.node_count > 0 ? "ok" : "warning",
    },
    { key: "observability", label: "Observability", status: "warning" },
    { key: "eval", label: "Eval", status: "ok" },
    { key: "rollback", label: "Rollback", status: "ok" },
  ];
}

function GateBadges({ badges, hasErrors, hasWarnings }: { badges: ReadinessBadge[]; hasErrors: boolean; hasWarnings: boolean }) {
  const badgeState = (badge: ReadinessBadge): "✓" | "⚠" | "✗" => {
    if (badge.status === "error" || hasErrors) return "✗";
    if (badge.status === "warning" || hasWarnings) return "⚠";
    return "✓";
  };

  return (
    <div className="publish-gate-drawer__badges">
      {badges.map((badge) => (
        <div
          key={badge.key}
          className={`publish-gate-drawer__badge publish-gate-drawer__badge--${badge.status}`}
        >
          <span className="publish-gate-drawer__badge-label">
            {badge.label}
          </span>
          <span className="publish-gate-drawer__badge-status">
            {badgeState(badge)}
          </span>
        </div>
      ))}
    </div>
  );
}

function GateIssues({ className, title, issues }: { className: string; title: string; issues: GateIssue[] }) {
  return (
    <div className={className}>
      <strong>{title}</strong>
      <ul>
        {issues.map((issue, index) => (
          <li key={`${issue.code}-${index}`}>
            <strong>{issue.code}</strong>: {issue.message}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ReleaseNotes() {
  return (
    <label className="publish-gate-drawer__release-notes">
      <span>Release notes</span>
      <textarea
        rows={2}
        placeholder="Describe changes in this version..."
      />
    </label>
  );
}

export function PublishGateDrawer({
  report,
  onClose,
  onPublish,
  onPublishToStaging,
  busy,
}: PublishGateDrawerProps) {
  const hasErrors = (report.errors ?? []).length > 0;
  const hasWarnings = (report.warnings ?? []).length > 0;

  const badges = readinessBadges(report);

  const isPublishable = !hasErrors && report.valid && report.node_count > 0;

  return (
    <div className="publish-gate-drawer">
      <div className="publish-gate-drawer__header">
        <span className="publish-gate-drawer__title">Publish Gate</span>
        <button type="button" onClick={onClose}>✕</button>
      </div>

      <GateBadges badges={badges} hasErrors={hasErrors} hasWarnings={hasWarnings} />

      {(report.errors ?? []).length > 0 ? (
        <GateIssues className="publish-gate-drawer__issues" title="Blocking errors:" issues={report.errors} />
      ) : null}

      {(report.warnings ?? []).length > 0 ? (
        <GateIssues className="publish-gate-drawer__issues publish-gate-drawer__issues--warning" title="Warnings:" issues={report.warnings} />
      ) : null}

      <div className="publish-gate-drawer__actions">
        <button type="button" disabled={busy}>
          Run Eval Suite ▾
        </button>
        <ReleaseNotes />
        <div className="publish-gate-drawer__publish-btns">
          {onPublishToStaging ? (
            <button
              type="button"
              onClick={onPublishToStaging}
              disabled={busy || !isPublishable}
            >
              Publish to Staging
            </button>
          ) : null}
          <button
            type="button"
            className="admin-panel__button admin-panel__button--primary"
            onClick={onPublish}
            disabled={busy || !isPublishable}
          >
            {busy ? "Publishing..." : "Publish Directly"}
          </button>
        </div>
      </div>
    </div>
  );
}
