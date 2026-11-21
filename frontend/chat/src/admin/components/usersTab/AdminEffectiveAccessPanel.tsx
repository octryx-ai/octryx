import { useAdminNavigation } from "../../adminNavigation";
import { accessFixForRow } from "./identityPresentation";
import type { AdminEffectiveAccessRow } from "./identityTypes";

import "./identityPages.css";

type AdminEffectiveAccessPanelProps = {
  rows: AdminEffectiveAccessRow[];
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
};

function CheckIcon() {
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

function CrossIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      aria-hidden="true"
      width="10"
      height="10"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
    >
      <path d="M5.5 5.5 14.5 14.5M14.5 5.5 5.5 14.5" />
    </svg>
  );
}

export function AdminEffectiveAccessPanel({
  rows,
  loading,
  error,
  onRefresh,
}: AdminEffectiveAccessPanelProps) {
  const { openAdminTab } = useAdminNavigation();
  return (
    <div className="admin-users">
      <div className="admin-panel__section-header">
        <span>Access check ({rows.length})</span>
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={onRefresh}
          disabled={loading}
        >
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      {error ? <div className="admin-panel__error">{error}</div> : null}

      <table className="admin-panel__table">
        <thead>
          <tr>
            <th>User</th>
            <th>Access</th>
            <th>Roles &amp; groups</th>
            <th title="Assigned / visible workspaces">Workspaces (assigned / visible)</th>
            <th aria-label="Fix" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <AccessRow key={row.user.id} row={row} onOpenTab={openAdminTab} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AccessRow({
  row,
  onOpenTab,
}: {
  row: AdminEffectiveAccessRow;
  onOpenTab: ReturnType<typeof useAdminNavigation>["openAdminTab"];
}) {
  const fix = accessFixForRow(row);
  return (
    <tr
      className={row.user.is_active ? "" : "admin-panel__row--inactive"}
    >
      <td>
        <strong>{row.user.username}</strong>
        <br />
        <span
          className="admin-panel__cell--muted"
          style={{ fontSize: "var(--ds-text-xs)" }}
        >
          {row.user.email}
        </span>
        <br />
        <span
          className={`admin-panel__badge ${row.user.is_active ? "admin-panel__badge--active" : "admin-panel__badge--inactive"}`}
        >
          {row.user.is_active ? "Active" : "Inactive"}
        </span>
      </td>
      {/* Chat and admin access stacked in one cell (fits a 1031 px window). */}
      <td className="admin-users__access-cell">
        <AccessBadge allowed={row.effective.can_use_chat} label="Chat" />
        <AccessBadge allowed={row.effective.can_open_admin_panel} label="Admin" />
      </td>
      <td>
        <ChipList values={row.roles} empty="No role" />
        <ChipList values={row.groups} empty="—" />
      </td>
      <td className="admin-panel__cell--muted">
        {row.effective.assigned_project_count} /{" "}
        {row.effective.visible_project_count}
      </td>
      <td>
        {fix ? (
          <button
            type="button"
            className="admin-users__table-action"
            onClick={() => onOpenTab(fix.tab)}
          >
            {fix.label}
          </button>
        ) : null}
      </td>
    </tr>
  );
}

function AccessBadge({ allowed, label }: { allowed: boolean; label: string }) {
  return (
    <span
      className={`admin-panel__badge ${allowed ? "admin-panel__badge--active" : "admin-panel__badge--inactive"}`}
    >
      {allowed ? <CheckIcon /> : <CrossIcon />}{" "}
      {label} {allowed ? "allowed" : "blocked"}
    </span>
  );
}

function ChipList({ values, empty }: { values: string[]; empty: string }) {
  return (
    <div className="admin-users__permission-list">
      {values.length ? (
        values.map((value) => (
          <span key={value} className="admin-users__role-chip">
            {value}
          </span>
        ))
      ) : (
        <span className="admin-panel__cell--muted">{empty}</span>
      )}
    </div>
  );
}
