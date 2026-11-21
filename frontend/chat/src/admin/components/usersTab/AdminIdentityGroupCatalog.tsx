import { dataAccessAttributesLabel } from "./identityPresentation";
import type { AdminIdentityGroupRow } from "./identityTypes";

import "./identityPages.css";
import { EmptyLine } from "../../../layout/EmptyLine";

function EditIcon() {
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

type AdminIdentityGroupCatalogProps = {
  groups: AdminIdentityGroupRow[];
  onEditGroup: (group: AdminIdentityGroupRow) => void;
  onCreateGroup?: () => void;
};

export function AdminIdentityGroupCatalog({
  groups,
  onEditGroup,
  onCreateGroup,
}: AdminIdentityGroupCatalogProps) {
  if (groups.length === 0) {
    return (
      <EmptyLine text="No groups yet." action={onCreateGroup ? { label: "New group", onClick: onCreateGroup } : undefined}
        testId="groups-empty" />
    );
  }
  return (
    <table className="admin-panel__table admin-users__group-table">
      <thead>
        <tr>
          <th>Group</th>
          <th>Description</th>
          <th title="Key = value pairs that database row-level security rules can reference">
            Data access attributes
          </th>
          <th>Members</th>
          <th>Status</th>
          <th aria-label="Actions" />
        </tr>
      </thead>
      <tbody>
        {groups.map((group) => (
          <tr
            key={group.id}
            className={group.is_active ? "" : "admin-panel__row--inactive"}
          >
            <td>
              <strong>{group.name}</strong>
            </td>
            <td className="admin-panel__cell--muted">
              {group.description || "No description"}
            </td>
            <td className="admin-panel__cell--muted">
              {dataAccessAttributesLabel(group.rls_attributes)}
            </td>
            <td className="admin-panel__cell--muted">
              {group.member_count} member{group.member_count === 1 ? "" : "s"}
            </td>
            <td>
              <span
                className={`admin-panel__badge ${group.is_active ? "admin-panel__badge--active" : "admin-panel__badge--inactive"}`}
              >
                {group.is_active ? "Active" : "Inactive"}
              </span>
            </td>
            <td>
              <button
                type="button"
                className="admin-users__row-btn"
                title={`Edit group ${group.name}`}
                aria-label={`Edit group ${group.name}`}
                onClick={() => onEditGroup(group)}
              >
                <EditIcon />
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
