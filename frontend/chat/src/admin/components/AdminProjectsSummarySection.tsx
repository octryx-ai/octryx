import { useMemo, useState } from "react";

import type { AdminProjectQuality } from "../types/projectQualityTypes";
import { DataTable, type DataTableColumn } from "../../layout/DataTable";
import { StatusLabel } from "../../layout/StatusLabel";
import { TimeText } from "../utils/TimeText";
import { ActionMenu } from "./workflowSurfaces/ActionMenu";
import {
  DEFAULT_WORKSPACE_STATUS_FILTER,
  WORKSPACE_STATUS_FILTER_OPTIONS,
  asWorkspaceStatusFilter,
  countWorkspacesByStatus,
  filterWorkspaces,
  type WorkspaceStatusFilter,
} from "./projectsTab/workspaceListModel";
import {
  WORKSPACE_LIST_COLUMN_LABELS as COLUMNS,
  workspaceClassCell,
  workspaceListRow,
  type WorkspaceClasses,
  type WorkspaceListRow,
} from "./projectsTab/workspaceListRow";

import "./projectsTab/workspaceList.css";

// Admin › Workspaces (central configuration): one full-width table; a row opens the Workspace's side panel, the ⋯ menu holds
// Make default, Archive/Restore and Delete. Members and Updated show only when the list payload carries them.

export type WorkspaceProblemCounts = Record<string, { total: number; problem: number }>;

type AdminProjectsSummarySectionProps = {
  adminProjects: AdminProjectQuality[] | null | undefined;
  handleOpenProjectQualityForm: (project: AdminProjectQuality) => void;
  projectActionLoading?: string | null;
  onCreateWorkspace?: () => void;
  onArchiveProject?: (project: AdminProjectQuality) => void;
  onRestoreProject?: (project: AdminProjectQuality) => void;
  onMakeDefaultProject?: (project: AdminProjectQuality) => void;
  onDeleteProject?: (project: AdminProjectQuality) => void;
  // A Workspace created a moment ago: its row is selected so the person sees where it went.
  highlightedProjectId?: string | null;
  // Problems per Workspace id (Admin › Problems); null while unknown, so the column is left out.
  problemCounts?: WorkspaceProblemCounts | null;
  // Each Workspace's classification level; null while unknown.
  workspaceClasses?: WorkspaceClasses | null;
  // Opens the Workspace's classification setting (Set class / Show class in the Class column).
  onOpenClassification?: (project: AdminProjectQuality) => void;
};

type Row = { project: AdminProjectQuality; row: WorkspaceListRow };

export function AdminProjectsSummarySection({
  adminProjects,
  handleOpenProjectQualityForm,
  projectActionLoading,
  onCreateWorkspace,
  onArchiveProject,
  onRestoreProject,
  onMakeDefaultProject,
  onDeleteProject,
  highlightedProjectId = null,
  problemCounts = null,
  workspaceClasses = null,
  onOpenClassification,
}: AdminProjectsSummarySectionProps) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<WorkspaceStatusFilter>(DEFAULT_WORKSPACE_STATUS_FILTER);
  const counts = useMemo(() => countWorkspacesByStatus(adminProjects), [adminProjects]);
  const rows: Row[] = useMemo(
    () => filterWorkspaces(adminProjects, query, statusFilter).map((project) => ({ project, row: workspaceListRow(project) })),
    [adminProjects, query, statusFilter],
  );
  const hasMembers = rows.some((item) => item.row.members !== null);
  const hasUpdated = rows.some((item) => item.row.updatedAt !== null);

  const columns = workspaceColumns({ hasMembers, hasUpdated, problemCounts, workspaceClasses, onOpenClassification });
  const menu = (item: Row) =>
    workspaceRowMenu(item, { projectActionLoading, onMakeDefaultProject, onArchiveProject, onRestoreProject, onDeleteProject });

  return (
    <div className="admin-projects__list" data-testid="workspace-list">
      <div className="admin-projects__toolbar">
        <WorkspaceFilters query={query} setQuery={setQuery} statusFilter={statusFilter} setStatusFilter={setStatusFilter}
          counts={counts} />
        {onCreateWorkspace ? (
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" onClick={onCreateWorkspace}
            data-testid="workspace-create">
            Create workspace
          </button>
        ) : null}
      </div>
      <DataTable<Row>
        label="Workspaces"
        columns={columns}
        rows={rows}
        rowKey={({ row }) => row.id}
        onOpen={({ project }) => handleOpenProjectQualityForm(project)}
        selectedKey={highlightedProjectId}
        rowMenu={menu}
        testId="workspace-table"
        empty={
          counts.all === 0
            ? { text: "No workspaces yet.", action: onCreateWorkspace ? { label: "Create workspace", onClick: onCreateWorkspace } : undefined }
            : { text: "No workspace matches this search or filter." }
        }
      />
    </div>
  );
}

type ColumnOptions = Pick<AdminProjectsSummarySectionProps, "onOpenClassification"> & {
  hasMembers: boolean;
  hasUpdated: boolean;
  problemCounts: WorkspaceProblemCounts | null;
  workspaceClasses: WorkspaceClasses | null;
};

const NAME_COLUMN: DataTableColumn<Row> = {
  key: "name",
  header: COLUMNS.workspace,
  grow: true,
  render: ({ row }) => (
    <span className="admin-projects__name-cell" title={row.descriptionTitle || undefined}>
      <strong>{row.name}</strong>
      {row.badges.map((badge) => (
        <StatusLabel key={badge} label={badge.charAt(0).toUpperCase() + badge.slice(1)} tone="neutral" />
      ))}
      {row.isActive ? null : <StatusLabel label="Archived" />}
    </span>
  ),
};

function workspaceColumns(options: ColumnOptions): DataTableColumn<Row>[] {
  const { hasMembers, hasUpdated, problemCounts } = options;
  return [
    NAME_COLUMN,
    classColumn(options),
    ...(hasMembers
      ? [{ key: "members", header: COLUMNS.members, align: "end" as const, nowrap: true,
          render: ({ row }: Row) => (row.members === null ? "—" : String(row.members)) }]
      : []),
    ...(problemCounts
      ? [{
          key: "problems",
          header: COLUMNS.problems,
          nowrap: true,
          render: ({ row }: Row) => {
            const entry = problemCounts[row.id];
            if (!entry || entry.total === 0) return "None";
            return <StatusLabel label={`${entry.total}`} tone={entry.problem > 0 ? "problem" : "attention"}
              title={`${entry.total} open: ${entry.problem} problems, ${entry.total - entry.problem} to look at`} />;
          },
        }]
      : []),
    ...(hasUpdated
      ? [{ key: "updated", header: COLUMNS.updated, nowrap: true,
          render: ({ row }: Row) => <TimeText value={row.updatedAt} mode="recent" /> }]
      : []),
  ];
}

function classColumn({ workspaceClasses, onOpenClassification }: ColumnOptions): DataTableColumn<Row> {
  return { key: "class", header: COLUMNS.class, nowrap: true, render: ({ project, row }) => {
    // A level in words, or "Not set" with the way to set it; never a bare dash.
    const cell = workspaceClassCell(row, workspaceClasses);
    const open = cell.action && onOpenClassification ? (
      <button type="button" className="ds-link-button" data-testid={`workspace-class-${cell.action}-${row.id}`}
        onClick={(event) => { event.stopPropagation(); onOpenClassification(project); }}>
        {cell.action === "set" ? "Set class" : "Show class"}
      </button>
    ) : null;
    return (
      <span className="admin-projects__class-cell" title={cell.title || undefined}>
        {cell.label ? <span className={cell.action === "set" ? "admin-projects__class-unset" : undefined}>{cell.label}</span> : null}
        {open}
      </span>
    );
  } };
}

type MenuHandlers = Pick<
  AdminProjectsSummarySectionProps,
  "projectActionLoading" | "onMakeDefaultProject" | "onArchiveProject" | "onRestoreProject" | "onDeleteProject"
>;

function workspaceRowMenu({ project, row }: Row, handlers: MenuHandlers) {
  const { projectActionLoading, onMakeDefaultProject, onArchiveProject, onRestoreProject, onDeleteProject } = handlers;
  const archiving = projectActionLoading === `archive:${project.id}`;
  const restoring = projectActionLoading === `restore:${project.id}`;
  const deleting = projectActionLoading === `delete:${project.id}`;
  const makingDefault = projectActionLoading === `default:${project.id}`;
  return (
    <ActionMenu
      row={{ objectName: row.name }}
      items={[
        {
          label: project.is_default ? "Default workspace" : makingDefault ? "Saving…" : "Make default",
          disabled: Boolean(project.is_default) || !project.is_active || makingDefault,
          onSelect: () => onMakeDefaultProject?.(project),
        },
        project.is_active
          ? {
              label: archiving ? "Archiving…" : "Archive…",
              danger: false,
              disabled: Boolean(project.is_system || project.is_default) || archiving,
              onSelect: () => onArchiveProject?.(project),
            }
          : { label: restoring ? "Restoring…" : "Restore", disabled: restoring, onSelect: () => onRestoreProject?.(project) },
        {
          label: deleting ? "Deleting…" : "Delete…",
          danger: true,
          disabled: Boolean(project.is_system || project.is_default) || deleting,
          onSelect: () => onDeleteProject?.(project),
        },
      ]}
    />
  );
}

function WorkspaceFilters({
  query,
  setQuery,
  statusFilter,
  setStatusFilter,
  counts,
}: {
  query: string;
  setQuery: (value: string) => void;
  statusFilter: WorkspaceStatusFilter;
  setStatusFilter: (value: WorkspaceStatusFilter) => void;
  counts: ReturnType<typeof countWorkspacesByStatus>;
}) {
  return (
    <section className="admin-users__toolbar" aria-label="Filter workspaces">
      <input
        className="admin-users__toolbar-input"
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search workspaces..."
        aria-label="Search workspaces"
      />
      <select
        className="admin-users__toolbar-select"
        value={statusFilter}
        onChange={(event) => setStatusFilter(asWorkspaceStatusFilter(event.target.value))}
        aria-label="Filter workspace status"
      >
        {WORKSPACE_STATUS_FILTER_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label} ({counts[option.value]})
          </option>
        ))}
      </select>
    </section>
  );
}
