// Table of corporate identity profiles with per-type template counts and row actions.
import type { useAdminCorpIdentity } from "../../hooks/useAdminCorpIdentity";
import type { AdminCorpIdentityProfile, OfficeTemplateEntry, OfficeTemplateType } from "../../types/adminPanelTypes.runtimeCorp";
import { DocTypeIcon, EditIcon } from "./corpIdentityIcons";

type CorpIdentityState = ReturnType<typeof useAdminCorpIdentity>;

const DOC_TYPES: OfficeTemplateType[] = ["pptx", "docx", "xlsx"];

function templatesByType(profile: AdminCorpIdentityProfile) {
  return (profile.templates || {}) as Record<string, OfficeTemplateEntry[]>;
}

function totalTemplates(profile: AdminCorpIdentityProfile) {
  const t = templatesByType(profile);
  return (t.pptx?.length || 0) + (t.docx?.length || 0) + (t.xlsx?.length || 0);
}

export function CorpProfilesTable({ state }: { state: CorpIdentityState }) {
  return (
    <table className="admin-panel__table">
      <thead>
        <tr>
          <th>Profile</th>
          <th>Theme</th>
          <th>Font</th>
          <th>Templates</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {state.corpIdentityProfiles.map((profile) => {
          const count = totalTemplates(profile);
          const t = templatesByType(profile);
          const summary = profile.summary || {};
          return (
            <tr key={profile.id}>
              <td>
                <strong>{profile.name}</strong>
                {profile.is_default ? (
                  <span className="admin-panel__badge admin-panel__badge--active corp-default-badge">
                    Default
                  </span>
                ) : null}
              </td>
              <td className="admin-panel__cell--muted">
                {summary.theme_name || "—"}
              </td>
              <td className="admin-panel__cell--muted">
                {summary.font_family || "—"}
              </td>
              <td className="admin-panel__cell--muted">
                <div className="corp-type-counts">
                  {DOC_TYPES.map((dt) => {
                    const items = t[dt] || [];
                    return items.length > 0 ? (
                      <span
                        key={dt}
                        className="corp-chip corp-type-counts__chip"
                        title={items
                          .map((i) => i.display_name || i.source_file_name)
                          .join(", ")}
                      >
                        <DocTypeIcon type={dt} />
                        {items.length}
                      </span>
                    ) : null;
                  })}
                  {count === 0 && <span className="corp-type-counts__none">none</span>}
                </div>
              </td>
              <td>
                <div className="admin-users__row-actions">
                  <button
                    type="button"
                    className="admin-users__row-btn"
                    title="Manage templates"
                    onClick={() => void state.loadCorpIdentityDetail(profile.id)}
                  >
                    <EditIcon />
                  </button>
                  {!profile.is_default ? (
                    <button
                      type="button"
                      className="admin-users__row-btn admin-users__row-btn--danger"
                      title="Delete profile"
                      onClick={() =>
                        void state.handleDeleteCorpIdentity(profile.id, profile.name)
                      }
                    >
                      ×
                    </button>
                  ) : null}
                </div>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
