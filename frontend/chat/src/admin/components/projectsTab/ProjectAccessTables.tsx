import type { AdminProjectAccessPayload, AdminProjectAccessUser } from "../../types/projectQualityTypes.access";
import type {
  AccessDraft,
  GroupAccessDraft,
  RoleAccessDraft,
} from "./projectAccessDrafts";
import { GroupAccessRow, RoleAccessRow, UserAccessRow } from "./projectAccessRows";
import { AccessCard, type RowsProps } from "./projectAccessTableParts";

export function DirectUserAccessTable({
  rows,
  userById,
  availableUsersForRow,
  onUpdate,
  onRemove,
  onAdd,
}: RowsProps<AccessDraft> & {
  userById: Record<string, AdminProjectAccessUser>;
  availableUsersForRow: (rowKey: string) => AdminProjectAccessUser[];
}) {
  return (
    <AccessCard
      title="Direct user access"
      badge="enforced"
      description="Named users and the workspace roles they hold here."
      addLabel="+ Add user"
      onAdd={onAdd}
    >
      <table className="admin-panel__table">
        <thead>
          <tr>
            <th>User</th>
            <th>Global roles</th>
            <th>Groups</th>
            <th>Workspace roles</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <UserAccessRow key={row.key} row={row} single={rows.length === 1} userById={userById}
              availableUsersForRow={availableUsersForRow} onUpdate={onUpdate} onRemove={onRemove} />
          ))}
          {rows.length === 0 ? (
            <tr>
              <td colSpan={5} className="project-access__muted">No user is assigned directly.</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </AccessCard>
  );
}

export function RoleAccessTable({
  rows,
  payload,
  availableRolesForRow,
  onUpdate,
  onRemove,
  onAdd,
}: RowsProps<RoleAccessDraft> & {
  payload: AdminProjectAccessPayload;
  availableRolesForRow: (rowKey: string) => AdminProjectAccessPayload["available_roles"];
}) {
  return (
    <AccessCard
      title="By global role"
      badge="enforced for matching users"
      description="Everyone with this global role gets the selected workspace roles."
      addLabel="+ Add role"
      onAdd={onAdd}
    >
      <table className="admin-panel__table">
        <thead>
          <tr>
            <th>Global role</th>
            <th>Description</th>
            <th>Workspace roles</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <RoleAccessRow key={row.key} row={row} single={rows.length === 1} payload={payload}
              availableRolesForRow={availableRolesForRow} onUpdate={onUpdate} onRemove={onRemove} />
          ))}
          {rows.length === 0 ? (
            <tr>
              <td colSpan={4} className="project-access__muted">No global role grants access.</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </AccessCard>
  );
}

export function GroupAccessTable({
  rows,
  payload,
  availableGroupsForRow,
  onUpdate,
  onRemove,
  onAdd,
}: RowsProps<GroupAccessDraft> & {
  payload: AdminProjectAccessPayload;
  availableGroupsForRow: (rowKey: string) => AdminProjectAccessPayload["available_groups"];
}) {
  return (
    <AccessCard
      title="By group"
      badge="enforced for active groups"
      description="Active members of the group get the selected workspace roles. Inactive groups grant nothing."
      addLabel="+ Add group"
      onAdd={onAdd}
    >
      <table className="admin-panel__table">
        <thead>
          <tr>
            <th>Group</th>
            <th>Status</th>
            <th>Workspace roles</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <GroupAccessRow key={row.key} row={row} single={rows.length === 1} payload={payload}
              availableGroupsForRow={availableGroupsForRow} onUpdate={onUpdate} onRemove={onRemove} />
          ))}
          {rows.length === 0 ? (
            <tr>
              <td colSpan={4} className="project-access__muted">No group grants access.</td>
            </tr>
          ) : null}
        </tbody>
      </table>
      {payload.rules.map((rule) => (
        <p key={rule} className="admin-panel__hint">
          {rule}
        </p>
      ))}
    </AccessCard>
  );
}
