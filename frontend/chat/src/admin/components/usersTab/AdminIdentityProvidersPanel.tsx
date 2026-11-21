import { useState, type Dispatch, type FormEvent, type SetStateAction } from "react";

import { DataTable, type DataTableColumn } from "../../../layout/DataTable";
import { EmptyLine } from "../../../layout/EmptyLine";
import { FormSection } from "../../../layout/FormSection";
import { SidePanel } from "../../../layout/SidePanel";
import { StatusLabel } from "../../../layout/StatusLabel";
import { AdminHeaderActions } from "../AdminHeaderSlot";
import { OidcRedirectUri } from "./AdminSsoSetupGuide";
import { IdentityProviderPanel } from "./IdentityProviderPanel";
import { OidcProviderCreateFields } from "./OidcProviderCreateFields";
import { EMPTY_OIDC_PROVIDER, type NewOidcProvider } from "./oidcProviderDraft";
import { SignInPasswordCard } from "./SignInPasswordCard";
import "./identityPages.css";
import type {
  AdminIdentityGroupRow,
  AdminIdentityProviderRow,
  AdminRoleRow,
} from "./identityTypes";
import type { IdentityProviderMappingDraft } from "./useAdminIdentityProviders";

type AdminIdentityProvidersPanelProps = {
  providers: AdminIdentityProviderRow[];
  drafts: Record<string, IdentityProviderMappingDraft>;
  roles: AdminRoleRow[];
  groups: AdminIdentityGroupRow[];
  loading: string | null;
  error: string | null;
  onRefresh: () => void;
  onCreateProvider: (payload: {
    name: string;
    issuerUrl: string;
    discoveryUrl: string;
    clientId: string;
    clientSecret: string;
    scopes: string;
  }) => void;
  onUpdateDraft: (
    providerId: string,
    updater: (
      draft: IdentityProviderMappingDraft,
    ) => IdentityProviderMappingDraft,
  ) => void;
  onSave: (provider: AdminIdentityProviderRow) => void;
};

const CREATE_FORM_ID = "oidc-provider-create-form";

const PROVIDER_COLUMNS: DataTableColumn<AdminIdentityProviderRow>[] = [
  { key: "name", header: "Name", grow: true, minWidth: "10rem", render: (provider) => provider.name },
  { key: "type", header: "Type", nowrap: true, render: (provider) => (provider.providerType || "").toUpperCase() || "—" },
  { key: "issuer", header: "Issuer", nowrap: true, clip: "20rem",
    render: (provider) => <span title={provider.issuerUrl || undefined}>{provider.issuerUrl || "Not set"}</span> },
  { key: "provisioning", header: "New users", nowrap: true,
    render: (provider) => (provider.autoProvisionUsers ? "Created at first sign-in" : "Must exist first") },
  { key: "state", header: "State", nowrap: true,
    render: (provider) => <StatusLabel label={provider.isActive ? "Active" : "Off"} /> },
];

function OidcProviderCreatePanel({ loading, newProvider, setNewProvider, onSubmit, onClose }: {
  loading: string | null;
  newProvider: NewOidcProvider;
  setNewProvider: Dispatch<SetStateAction<NewOidcProvider>>;
  onSubmit: (event: FormEvent) => void;
  onClose: () => void;
}) {
  return (
    <SidePanel
      title="Register OIDC provider"
      onClose={onClose}
      testId="oidc-provider-create-panel"
      footer={(
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
          <button
            type="submit"
            form={CREATE_FORM_ID}
            className="admin-panel__action-btn admin-panel__action-btn--primary"
            disabled={loading === "create"}
            data-testid="oidc-provider-create-submit"
          >
            {loading === "create" ? "Registering..." : "Register provider"}
          </button>
        </>
      )}
    >
      <form id={CREATE_FORM_ID} onSubmit={onSubmit} aria-label="Register OIDC provider">
        <FormSection title="At your identity provider">
          <OidcRedirectUri />
        </FormSection>
        <FormSection title="Provider">
          <OidcProviderCreateFields value={newProvider} onChange={setNewProvider} />
        </FormSection>
      </form>
    </SidePanel>
  );
}

function ProvidersHeaderActions({ onRefresh, onCreate }: { onRefresh: () => void; onCreate: () => void }) {
  return (
    <AdminHeaderActions>
      <button type="button" className="admin-panel__action-btn" onClick={onRefresh} data-testid="oidc-providers-refresh">
        Refresh
      </button>
      <button
        type="button"
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        onClick={onCreate}
        data-testid="oidc-provider-create-open"
      >
        Register OIDC provider
      </button>
    </AdminHeaderActions>
  );
}

export function AdminIdentityProvidersPanel({
  providers, drafts, roles, groups, loading, error, onRefresh, onCreateProvider, onUpdateDraft, onSave,
}: AdminIdentityProvidersPanelProps) {
  const [showCreate, setShowCreate] = useState(false);
  // Providers are table rows; a row opens its settings in the side panel (like users, roles, groups).
  const [openId, setOpenId] = useState<string | null>(null);
  const openProvider = providers.find((provider) => provider.id === openId) ?? null;
  const [newProvider, setNewProvider] = useState<NewOidcProvider>(EMPTY_OIDC_PROVIDER);

  const handleCreate = (event: FormEvent) => {
    event.preventDefault();
    onCreateProvider(newProvider);
    setNewProvider(EMPTY_OIDC_PROVIDER);
    setShowCreate(false);
  };

  const activeSsoProviders = loading === "load" && providers.length === 0 ? null
    : providers.filter((row) => (row.providerType || "").toLowerCase() === "oidc" && row.isActive).length;

  const closeCreate = () => setShowCreate(false);

  return (
    <>
    <ProvidersHeaderActions onRefresh={onRefresh} onCreate={() => setShowCreate(true)} />
    <section className="admin-users__providers">
      {error ? <div className="admin-panel__error">{error}</div> : null}
      {showCreate ? (
        <OidcProviderCreatePanel loading={loading} newProvider={newProvider} setNewProvider={setNewProvider}
          onSubmit={handleCreate} onClose={closeCreate} />
      ) : null}
      <DataTable<AdminIdentityProviderRow>
        label="Identity providers"
        testId="oidc-providers-table"
        loading={loading === "load" && providers.length === 0}
        rows={providers}
        rowKey={(provider) => provider.id}
        selectedKey={openId}
        onOpen={(provider) => setOpenId(provider.id)}
        empty={{ text: "No identity provider registered yet.", action: { label: "Register OIDC provider", onClick: () => setShowCreate(true) },
          testId: "oidc-providers-empty" }}
        columns={PROVIDER_COLUMNS}
      />
      {openProvider && drafts[openProvider.id] ? (
        <IdentityProviderPanel provider={openProvider} draft={drafts[openProvider.id]} roles={roles} groups={groups}
          saving={loading === `save:${openProvider.id}`} onUpdateDraft={onUpdateDraft} onSave={onSave}
          onClose={() => setOpenId(null)} />
      ) : null}
    </section>
    <SignInPasswordCard activeSsoProviders={activeSsoProviders} />
    </>
  );
}
