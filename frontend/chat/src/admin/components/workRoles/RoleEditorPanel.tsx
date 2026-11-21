import { SidePanel } from "../../../layout/SidePanel";
import { ConfirmDialog } from "../confirm/ConfirmDialog";
import { scopeText } from "./workRolesModel";
import { ErrorLine, RoleBadges } from "./WorkRolesParts";
import type { WorkFunction, WorkRole } from "./workRolesTypes";
import { useRoleEditor } from "./useRoleEditor";
import {
  RoleBasicsSection, RoleCommandRulesSection, RoleConnectionsSection, RoleEditorFooter, RoleFunctionsSection, RoleTrustedDialog, RoleTrustSection,
} from "./RoleEditorSections";

type Workspace = { id: string; name: string };

// The role editor (board 8): name, key on create, description, functions, write connections, command rules, the
// trusted switch (reason + confirm), active and delete. Trusted has its own endpoint and is never part of Save.
export function RoleEditorPanel({ role: initial, functions, workspaces, canEdit, defaultWorkspaceId = null, onClose, onSaved }: {
  role: WorkRole | null;
  functions: WorkFunction[];
  workspaces: Workspace[];
  canEdit: boolean;
  defaultWorkspaceId?: string | null;
  onClose: () => void;
  onSaved: (role: WorkRole | null) => void;
}) {
  const editor = useRoleEditor(initial, defaultWorkspaceId, onClose, onSaved);
  const { creating, role } = editor;
  const readOnly = !canEdit;
  const part = { editor, readOnly };
  return (
    <SidePanel title={creating ? "New role" : role!.name} subtitle={creating ? "A name plus the functions it may use." : scopeText(role!.workspace_id, workspaces)}
      onClose={onClose} footer={<RoleEditorFooter {...part} onClose={onClose} />} testId="role-editor">
      <div className="wr-form">
        {role ? <RoleBadges role={role} /> : null}
        <ErrorLine error={editor.error} />
        <RoleBasicsSection {...part} workspaces={workspaces} />
        <RoleFunctionsSection {...part} functions={functions} />
        <RoleConnectionsSection {...part} />
        <RoleCommandRulesSection {...part} />
        {role ? <RoleTrustSection {...part} role={role} /> : null}
      </div>

      {editor.trustedStep && role ? <RoleTrustedDialog editor={editor} role={role} /> : null}

      {editor.confirmDelete && role ? (
        <ConfirmDialog title={`Delete ${role.name}?`} confirmLabel="Delete role" busy={editor.busy} error={editor.deleteError}
          onCancel={() => editor.setConfirmDelete(false)} onConfirm={() => void editor.remove()}>
          <p>The role disappears from every Workspace. A role that is still assigned cannot be deleted; revoke its assignments first.</p>
        </ConfirmDialog>
      ) : null}
    </SidePanel>
  );
}
