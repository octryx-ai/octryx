import type { FormEvent } from "react";

import { AdminHeaderActions } from "../AdminHeaderSlot";
import { AdminGroupEditPanel } from "./AdminGroupEditPanel";
import { AdminIdentityGroupCatalog } from "./AdminIdentityGroupCatalog";
import { IdentityCreatePanel } from "./IdentityCreatePanel";
import type { AdminIdentityGroupRow } from "./identityTypes";

type AdminGroupsPanelProps = {
  groups: AdminIdentityGroupRow[];
  groupName: string;
  groupDescription: string;
  groupError: string | null;
  groupLoading: string | null;
  editingGroup: AdminIdentityGroupRow | null;
  showCreateGroup: boolean;
  setGroupName: (value: string) => void;
  setGroupDescription: (value: string) => void;
  setShowCreateGroup: (value: boolean | ((value: boolean) => boolean)) => void;
  onCreateGroup: (event: FormEvent) => void;
  onRefresh: () => void;
  onEditGroup: (group: AdminIdentityGroupRow) => void;
  onCloseEditPanel: () => void;
  onUpdateGroup: (
    group: AdminIdentityGroupRow,
    payload: {
      description?: string;
      rls_attributes?: Array<{ key: string; value: string }>;
    },
  ) => void;
  onToggleGroup: (group: AdminIdentityGroupRow) => void;
  onDeleteGroup: (group: AdminIdentityGroupRow) => void;
};

export function AdminGroupsPanel({
  groups,
  groupName,
  groupDescription,
  groupError,
  groupLoading,
  editingGroup,
  showCreateGroup,
  setGroupName,
  setGroupDescription,
  setShowCreateGroup,
  onCreateGroup,
  onRefresh,
  onEditGroup,
  onCloseEditPanel,
  onUpdateGroup,
  onToggleGroup,
  onDeleteGroup,
}: AdminGroupsPanelProps) {
  return (
    <div className="admin-users">
      <AdminHeaderActions>
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={() => setShowCreateGroup(true)}
          data-testid="group-create-open"
        >
          + New group
        </button>
      </AdminHeaderActions>
      <div className="admin-panel__section-header">
        <span>Groups ({groups.length})</span>
      </div>

      {groupError && !showCreateGroup ? (
        <div className="admin-panel__error">{groupError}</div>
      ) : null}

      {showCreateGroup ? (
        <GroupCreatePanel groupName={groupName} groupDescription={groupDescription} groupError={groupError} groupLoading={groupLoading}
          setGroupName={setGroupName} setGroupDescription={setGroupDescription} setShowCreateGroup={setShowCreateGroup}
          onCreateGroup={onCreateGroup} />
      ) : null}

      <AdminIdentityGroupCatalog
        groups={groups}
        onEditGroup={onEditGroup}
        onCreateGroup={showCreateGroup ? undefined : () => setShowCreateGroup(true)}
      />

      {editingGroup ? (
        <GroupEditPanel editingGroup={editingGroup} groupLoading={groupLoading} onCloseEditPanel={onCloseEditPanel}
          onUpdateGroup={onUpdateGroup} onToggleGroup={onToggleGroup} onDeleteGroup={onDeleteGroup} />
      ) : null}
    </div>
  );
}

// The "New group" side panel: name and description.
function GroupCreatePanel({ groupName, groupDescription, groupError, groupLoading, setGroupName, setGroupDescription,
  setShowCreateGroup, onCreateGroup }: Pick<AdminGroupsPanelProps, "groupName" | "groupDescription" | "groupError" | "groupLoading"
  | "setGroupName" | "setGroupDescription" | "setShowCreateGroup" | "onCreateGroup">) {
  return (
    <IdentityCreatePanel title="New group" section="Group" formId="admin-group-create-form" submitLabel="Create group"
      busyLabel="Creating…" busy={groupLoading === "create"} error={groupError} onSubmit={onCreateGroup}
      onClose={() => setShowCreateGroup(false)} testId="group-create-panel">
      <label className="admin-panel__field">
        <span>
          Group name <span className="admin-users__form-required" aria-hidden="true">*</span>
        </span>
        <input
          value={groupName}
          onChange={(e) => setGroupName(e.target.value)}
          required
        />
      </label>
      <label className="admin-panel__field">
        <span>Description</span>
        <input
          value={groupDescription}
          onChange={(e) => setGroupDescription(e.target.value)}
        />
      </label>
    </IdentityCreatePanel>
  );
}

// The edit panel of one group; deleting the group also closes it.
function GroupEditPanel({ editingGroup, groupLoading, onCloseEditPanel, onUpdateGroup, onToggleGroup, onDeleteGroup }: {
  editingGroup: AdminIdentityGroupRow;
} & Pick<AdminGroupsPanelProps, "groupLoading" | "onCloseEditPanel" | "onUpdateGroup" | "onToggleGroup" | "onDeleteGroup">) {
  return (
    <AdminGroupEditPanel
      group={editingGroup}
      groupLoading={groupLoading}
      onClose={onCloseEditPanel}
      onUpdateGroup={(group, payload) => onUpdateGroup(group, payload)}
      onToggleGroup={onToggleGroup}
      onDeleteGroup={(group) => {
        onDeleteGroup(group);
        onCloseEditPanel();
      }}
    />
  );
}
