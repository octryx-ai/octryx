import type { AdminProjectAccessPayload, AdminProjectAccessUser } from "../../types/projectQualityTypes.access";
import { ProjectRoleChips } from "./ProjectRoleChips";
import type {
  AccessDraft,
  GroupAccessDraft,
  RoleAccessDraft,
} from "./projectAccessDrafts";
import { RemoveButton, type RowsProps } from "./projectAccessTableParts";

// One row of each Workspace access table: who or what is granted (a picker while the row is new), the facts the
// platform knows about it, its Workspace roles and Remove (off for the only, still empty row).

type RowProps<T> = Pick<RowsProps<T>, "onUpdate" | "onRemove"> & { row: T; single: boolean };

export function UserAccessRow({ row, single, userById, availableUsersForRow, onUpdate, onRemove }: RowProps<AccessDraft> & {
  userById: Record<string, AdminProjectAccessUser>;
  availableUsersForRow: (rowKey: string) => AdminProjectAccessUser[];
}) {
  const user = row.user_id ? userById[row.user_id] : null;
  const name = user ? user.display_name || user.username : "";
  return (
    <tr>
      <td>
        {user ? (
          <>
            <strong>{name}</strong>
            <small className="project-access__muted">
              {user.username} · {user.email}
              {!user.is_active ? " · inactive" : ""}
            </small>
          </>
        ) : (
          <select
            className="admin-panel__input"
            value={row.user_id}
            aria-label="Select user"
            onChange={(event) => onUpdate(row.key, { user_id: event.target.value })}
          >
            <option value="">Select user</option>
            {availableUsersForRow(row.key).map((option) => (
              <option key={option.id} value={option.id}>
                {option.display_name || option.username}
              </option>
            ))}
          </select>
        )}
      </td>
      <td className="project-access__muted">{user?.roles.join(", ") || "—"}</td>
      <td className="project-access__muted">{user?.groups.join(", ") || "—"}</td>
      <td>
        <ProjectRoleChips
          label={`Workspace roles for ${name || "new user"}`}
          value={row.project_roles}
          disabled={!row.user_id}
          onChange={(roles) => onUpdate(row.key, { project_roles: roles })}
        />
      </td>
      <td>
        <RemoveButton
          label={`Remove ${name || "user row"}`}
          disabled={single && !row.user_id}
          onClick={() => onRemove(row.key)}
        />
      </td>
    </tr>
  );
}

export function RoleAccessRow({ row, single, payload, availableRolesForRow, onUpdate, onRemove }: RowProps<RoleAccessDraft> & {
  payload: AdminProjectAccessPayload;
  availableRolesForRow: (rowKey: string) => AdminProjectAccessPayload["available_roles"];
}) {
  const role = row.role_id ? payload.available_roles.find((item) => item.id === row.role_id) : null;
  return (
    <tr>
      <td>
        {role ? (
          <strong>{role.name}</strong>
        ) : (
          <select
            className="admin-panel__input"
            value={row.role_id}
            aria-label="Select global role"
            onChange={(event) => onUpdate(row.key, { role_id: event.target.value })}
          >
            <option value="">Select role</option>
            {availableRolesForRow(row.key).map((option) => (
              <option key={option.id} value={option.id}>
                {option.name}
              </option>
            ))}
          </select>
        )}
      </td>
      <td className="project-access__muted">{role?.description || "—"}</td>
      <td>
        <ProjectRoleChips
          label={`Workspace roles for ${role?.name || "new role"}`}
          value={row.project_roles}
          disabled={!row.role_id}
          onChange={(roles) => onUpdate(row.key, { project_roles: roles })}
        />
      </td>
      <td>
        <RemoveButton
          label={`Remove ${role?.name || "role row"}`}
          disabled={single && !row.role_id}
          onClick={() => onRemove(row.key)}
        />
      </td>
    </tr>
  );
}

export function GroupAccessRow({ row, single, payload, availableGroupsForRow, onUpdate, onRemove }: RowProps<GroupAccessDraft> & {
  payload: AdminProjectAccessPayload;
  availableGroupsForRow: (rowKey: string) => AdminProjectAccessPayload["available_groups"];
}) {
  const group = row.group_id ? payload.available_groups.find((item) => item.id === row.group_id) : null;
  return (
    <tr>
      <td>
        {group ? (
          <>
            <strong>{group.name}</strong>
            <small className="project-access__muted">{group.description || "No description"}</small>
          </>
        ) : (
          <select
            className="admin-panel__input"
            value={row.group_id}
            aria-label="Select group"
            onChange={(event) => onUpdate(row.key, { group_id: event.target.value })}
          >
            <option value="">Select group</option>
            {availableGroupsForRow(row.key).map((option) => (
              <option key={option.id} value={option.id}>
                {option.name}
              </option>
            ))}
          </select>
        )}
      </td>
      <td className="project-access__muted">
        {group ? (group.is_active ? "Active" : "Inactive") : "—"}
      </td>
      <td>
        <ProjectRoleChips
          label={`Workspace roles for ${group?.name || "new group"}`}
          value={row.project_roles}
          disabled={!row.group_id}
          onChange={(roles) => onUpdate(row.key, { project_roles: roles })}
        />
      </td>
      <td>
        <RemoveButton
          label={`Remove ${group?.name || "group row"}`}
          disabled={single && !row.group_id}
          onClick={() => onRemove(row.key)}
        />
      </td>
    </tr>
  );
}
