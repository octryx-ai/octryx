import type { AdminUserOidcIdentityRow } from "./identityTypes";
import { formatDateTime } from "../../utils/dateTime";

type AdminUserOidcIdentitiesPanelProps = {
  identities: AdminUserOidcIdentityRow[];
  loading: boolean;
  error: string | null;
};

function formatDate(value: string | null) {
  if (!value) return "Never";
  return formatDateTime(value);
}

function formatProfile(profile: Record<string, unknown>) {
  return JSON.stringify(profile || {}, null, 2);
}

export function AdminUserOidcIdentitiesPanel({
  identities,
  loading,
  error,
}: AdminUserOidcIdentitiesPanelProps) {
  return (
    <section className="user-edit-panel__section">
      <p className="user-edit-panel__section-label">OIDC identity debug</p>
      {loading ? (
        <p className="admin-panel__cell--muted" style={{ fontSize: "var(--ds-text-sm)" }}>
          Loading OIDC identities...
        </p>
      ) : null}
      {error ? <p className="admin-panel__error">{error}</p> : null}
      {!loading && identities.length === 0 ? (
        <p className="admin-panel__cell--muted" style={{ fontSize: "var(--ds-text-sm)" }}>
          No OIDC identity is linked to this user.
        </p>
      ) : null}
      {identities.map((identity) => (
        <article key={identity.id} className="user-edit-panel__oidc-card">
          <div className="user-edit-panel__oidc-header">
            <div>
              <strong>{identity.provider_name || "OIDC provider"}</strong>
              <span>{identity.provider_type || "oidc"}</span>
            </div>
            <span className="admin-panel__badge admin-panel__badge--active">
              Last login {formatDate(identity.last_login_at)}
            </span>
          </div>
          <dl className="user-edit-panel__oidc-grid">
            <div>
              <dt>Subject</dt>
              <dd>{identity.subject || "-"}</dd>
            </div>
            <div>
              <dt>Email</dt>
              <dd>{identity.external_email || "-"}</dd>
            </div>
            <div>
              <dt>Username</dt>
              <dd>{identity.external_username || "-"}</dd>
            </div>
            <div>
              <dt>External groups</dt>
              <dd>
                {identity.external_groups.length > 0
                  ? identity.external_groups.join(", ")
                  : "-"}
              </dd>
            </div>
          </dl>
          <details className="user-edit-panel__oidc-profile">
            <summary>Raw claims</summary>
            <pre>{formatProfile(identity.profile)}</pre>
          </details>
        </article>
      ))}
    </section>
  );
}
