// Settings side panel of one identity provider: provider fields, claim mappings, provisioning and group mappings.
import { FormSection } from "../../../layout/FormSection";
import { SidePanel } from "../../../layout/SidePanel";
import { GroupMappingEditor } from "./GroupMappingEditor";
import type {
  AdminIdentityGroupRow,
  AdminIdentityProviderRow,
  AdminRoleRow,
} from "./identityTypes";
import type { IdentityProviderMappingDraft } from "./useAdminIdentityProviders";

const CLAIM_FIELDS = [
  ["subject", "Subject claim"],
  ["email", "Email claim"],
  ["username", "Username claim"],
  ["display_name", "Display-name claim"],
  ["groups", "Groups claim"],
] as const;

function toggleSetValue(
  current: Set<string>,
  value: string,
  checked: boolean,
): Set<string> {
  const next = new Set(current);
  if (checked) {
    next.add(value);
  } else {
    next.delete(value);
  }
  return next;
}

type Update = (patch: Partial<IdentityProviderMappingDraft>) => void;

// One identity provider's settings in the side panel (it was a large inline form card): the
// provider, its claim mappings, how new users are provisioned and the group mappings; Save changes bottom right.
export function IdentityProviderPanel({ provider, draft, roles, groups, saving, onUpdateDraft, onSave, onClose }: {
  provider: AdminIdentityProviderRow;
  draft: IdentityProviderMappingDraft;
  roles: AdminRoleRow[];
  groups: AdminIdentityGroupRow[];
  saving: boolean;
  onUpdateDraft: (
    providerId: string,
    updater: (
      draft: IdentityProviderMappingDraft,
    ) => IdentityProviderMappingDraft,
  ) => void;
  onSave: (provider: AdminIdentityProviderRow) => void;
  onClose: () => void;
}) {
  const update = (patch: Partial<IdentityProviderMappingDraft>) => onUpdateDraft(provider.id, (current) => ({ ...current, ...patch }));
  return (
    <SidePanel
      title={provider.name}
      subtitle={`${(provider.providerType || "").toUpperCase()} · ${provider.issuerUrl || "issuer not set"}`}
      onClose={onClose}
      testId="oidc-provider-panel"
      footer={(
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={saving}
            onClick={() => onSave(provider)} data-testid="oidc-provider-save">
            {saving ? "Saving..." : "Save changes"}
          </button>
        </>
      )}
    >
      <div className="admin-users__provider-form">
      <ProviderSection draft={draft} update={update} />
      <ClaimMappingsSection draft={draft} update={update} />
      <NewUsersSection draft={draft} roles={roles} groups={groups} update={update} />
      <FormSection title="Group mappings">
        <GroupMappingEditor title="External group to local roles" testId={`provider-role-mappings-${provider.id}`}
          rows={draft.groupRoleMappings}
          options={roles.map((role) => ({ value: role.name, label: role.name }))}
          onChange={(rows) => update({ groupRoleMappings: rows })} />
        <GroupMappingEditor title="External group to local groups" testId={`provider-group-mappings-${provider.id}`}
          rows={draft.groupGroupMappings}
          options={groups.map((group) => ({ value: group.id, label: group.name }))}
          onChange={(rows) => update({ groupGroupMappings: rows })} />
      </FormSection>
      </div>
    </SidePanel>
  );
}

function ProviderSection({ draft, update }: { draft: IdentityProviderMappingDraft; update: Update }) {
  const field = (label: string, key: "name" | "issuerUrl" | "discoveryUrl" | "clientId" | "scopes") => (
    <label className="admin-panel__field">
      <span>{label}</span>
      <input className="admin-panel__input" value={draft[key]} onChange={(event) => update({ [key]: event.target.value })} />
    </label>
  );
  return (
    <FormSection title="Provider">
      <label className="admin-panel__checkbox">
        <input type="checkbox" checked={draft.isActive} onChange={(event) => update({ isActive: event.target.checked })} />
        <span>Active</span>
      </label>
      {field("Provider name", "name")}
      {field("Issuer URL", "issuerUrl")}
      {field("Discovery URL", "discoveryUrl")}
      {field("Client ID", "clientId")}
      {field("Scopes", "scopes")}
    </FormSection>
  );
}

function ClaimMappingsSection({ draft, update }: { draft: IdentityProviderMappingDraft; update: Update }) {
  return (
    <FormSection title="Claim mappings">
      {CLAIM_FIELDS.map(([key, label]) => (
        <label key={key} className="admin-panel__field">
          <span>{label}</span>
          <input
            className="admin-panel__input"
            value={draft.claimMappings[key] || ""}
            onChange={(event) => update({ claimMappings: { ...draft.claimMappings, [key]: event.target.value } })}
          />
        </label>
      ))}
    </FormSection>
  );
}

function NewUsersSection({ draft, roles, groups, update }: {
  draft: IdentityProviderMappingDraft;
  roles: AdminRoleRow[];
  groups: AdminIdentityGroupRow[];
  update: Update;
}) {
  return (
    <FormSection title="New users">
      <label className="admin-panel__checkbox">
        <input type="checkbox" checked={draft.autoProvisionUsers} onChange={(event) => update({ autoProvisionUsers: event.target.checked })} />
        <span>Create users at their first sign-in</span>
      </label>
      <div className="admin-users__mapping-columns">
        <div>
          <strong>Default roles</strong>
          <div className="admin-users__provider-checks">
            {roles.map((role) => (
              <label key={role.id} className="admin-users__role-chip admin-panel__checkbox">
                <input
                  type="checkbox"
                  checked={draft.defaultRoles.has(role.name)}
                  onChange={(event) => update({ defaultRoles: toggleSetValue(draft.defaultRoles, role.name, event.target.checked) })}
                />
                <span>{role.name}</span>
              </label>
            ))}
          </div>
        </div>
        <div>
          <strong>Default groups</strong>
          <div className="admin-users__provider-checks">
            {groups.map((group) => (
              <label key={group.id} className="admin-users__role-chip admin-panel__checkbox">
                <input
                  type="checkbox"
                  checked={draft.defaultGroupIds.has(group.id)}
                  onChange={(event) => update({ defaultGroupIds: toggleSetValue(draft.defaultGroupIds, group.id, event.target.checked) })}
                />
                <span>{group.name}</span>
              </label>
            ))}
          </div>
        </div>
      </div>
    </FormSection>
  );
}
