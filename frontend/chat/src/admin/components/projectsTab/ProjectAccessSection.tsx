import { useAdminNavigation, type AdminNavigation } from "../../adminNavigation";
import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import type { AdminProjectAccessPayload } from "../../types/projectQualityTypes.access";
import type { AdminProjectQuality } from "../../types/projectQualityTypes";
import {
  DirectUserAccessTable,
  GroupAccessTable,
  RoleAccessTable,
} from "./ProjectAccessTables";
import { useProjectAccess, type ProjectAccessState } from "./useProjectAccess";

import "./projectAccess.css";

type ProjectAccessSectionProps = {
  ctx: Record<string, unknown>;
};

// The title with Refresh, what workspace roles mean, and how many users, roles and groups are assigned.
function ProjectAccessSummary({ access, onRefresh, openAdminTab }: {
  access: ProjectAccessState;
  onRefresh: () => void;
  openAdminTab: AdminNavigation["openAdminTab"];
}) {
  const { drafts, loading, userById } = access;
  const assignedUsers = drafts.direct.filter((row) => row.user_id).length;
  const activeAssignedUsers = drafts.direct.filter((row) => userById[row.user_id]?.is_active).length;
  return (
    <>
      <div className="admin-panel__section-header">
        <span>Workspace access</span>
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={onRefresh}
          disabled={loading}
        >
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>
      <p className="admin-panel__hint">
        Platform access (People &amp; sign-in → Platform access) decides what someone may do on the
        platform; workspace roles decide what they may do inside this
        workspace: <strong>owner</strong> also edits workspace knowledge,{" "}
        <strong>member</strong> uses the allowed tools, <strong>viewer</strong>{" "}
        is limited to read-only tools.{" "}
        <button type="button" className="project-access__link" onClick={() => openAdminTab("identityRoles")}>
          Open Platform access
        </button>
      </p>
      <div className="admin-inline-actions">
        <span className="admin-panel__badge admin-panel__badge--inactive">
          {assignedUsers} users ({activeAssignedUsers} active)
        </span>
        <span className="admin-panel__badge admin-panel__badge--inactive">
          {drafts.roles.filter((row) => row.role_id).length} global roles
        </span>
        <span className="admin-panel__badge admin-panel__badge--inactive">
          {drafts.groups.filter((row) => row.group_id).length} groups
        </span>
      </div>
    </>
  );
}

// The three assignment tables (groups only where the server supports them) and Save.
function ProjectAccessEditor({ access, payload }: { access: ProjectAccessState; payload: AdminProjectAccessPayload }) {
  const { drafts, saving, userById, usedIds, updateRow, removeRow, addRow, saveAccess } = access;
  return (
    <>
        <DirectUserAccessTable
          rows={drafts.direct}
          userById={userById}
          availableUsersForRow={(rowKey) => {
            const used = usedIds("direct", rowKey);
            return payload.available_users.filter((user) => !used.has(user.id));
          }}
          onUpdate={(key, patch) => updateRow("direct", key, patch)}
          onRemove={(key) => removeRow("direct", key)}
          onAdd={() => addRow("direct")}
        />
        <RoleAccessTable
          rows={drafts.roles}
          payload={payload}
          availableRolesForRow={(rowKey) => {
            const used = usedIds("roles", rowKey);
            return payload.available_roles.filter((role) => !used.has(role.id));
          }}
          onUpdate={(key, patch) => updateRow("roles", key, patch)}
          onRemove={(key) => removeRow("roles", key)}
          onAdd={() => addRow("roles")}
        />
        {payload.group_assignments_supported ? (
          <GroupAccessTable
            rows={drafts.groups}
            payload={payload}
            availableGroupsForRow={(rowKey) => {
              const used = usedIds("groups", rowKey);
              return payload.available_groups.filter((group) => !used.has(group.id));
            }}
            onUpdate={(key, patch) => updateRow("groups", key, patch)}
            onRemove={(key) => removeRow("groups", key)}
            onAdd={() => addRow("groups")}
          />
        ) : null}
        <div className="project-access__footer">
          <span className="admin-panel__hint">Changes apply after saving.</span>
          <button
            type="button"
            className="admin-panel__action-btn admin-panel__action-btn--primary"
            onClick={() => void saveAccess()}
            disabled={saving}
          >
            {saving ? "Saving..." : "Save workspace access"}
          </button>
        </div>
    </>
  );
}

export function ProjectAccessSection({ ctx }: ProjectAccessSectionProps) {
  const { configuringProjectQuality, readJson } = ctx as {
    configuringProjectQuality: AdminProjectQuality | null;
    readJson: ReadJsonFn;
  };
  const { openAdminTab } = useAdminNavigation();
  const projectId = configuringProjectQuality?.id || "";
  const access = useProjectAccess(projectId, readJson);
  const { payload, loading, error, loadAccess } = access;

  return (
    <section className="admin-modal__stack project-access">
      <ProjectAccessSummary access={access} onRefresh={() => void loadAccess()} openAdminTab={openAdminTab} />

      {error ? <div className="admin-panel__error">{error}</div> : null}
      {loading && !payload ? <div className="admin-panel__empty-state">Loading workspace access...</div> : null}

      {payload ? <ProjectAccessEditor access={access} payload={payload} /> : null}
    </section>
  );
}
