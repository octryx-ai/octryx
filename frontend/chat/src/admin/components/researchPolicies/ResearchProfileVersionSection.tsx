// Research profile panel: version selector with diagnostics status, publish button, errors and warnings.
import { FormSection } from "../../../layout/FormSection";
import type { useAdminResearchPolicies } from "../../hooks/useAdminResearchPolicies";

function statusClass(status: string) {
  return status === "valid" || status === "published" || status === "active"
    ? "admin-panel__badge admin-panel__badge--active"
    : "admin-panel__badge";
}

type ResearchProfileVersionSectionProps = {
  state: ReturnType<typeof useAdminResearchPolicies>;
};

export function ResearchProfileVersionSection({ state }: ResearchProfileVersionSectionProps) {
  return (
    <FormSection title="Version">
      <div className="user-edit-panel__row">
        <select
          className="admin-panel__input"
          value={state.selectedVersion?.id || ""}
          onChange={(e) => state.setSelectedVersionId(e.target.value)}
        >
          {(state.selectedProfile?.versions || []).map((version) => (
            <option key={version.id} value={version.id}>
              v{version.version} · {version.status} ·{" "}
              {version.diagnostics.status}
            </option>
          ))}
        </select>
        <span
          className={statusClass(
            state.selectedVersion?.diagnostics.status || "invalid",
          )}
        >
          {state.selectedVersion?.diagnostics.status || "invalid"}
        </span>
        {state.selectedVersion?.status === "draft" ? (
          <button
            type="button"
            className="admin-panel__action-btn"
            disabled={state.saving}
            onClick={() => void state.publishSelectedVersion()}
          >
            Publish
          </button>
        ) : null}
      </div>

      {/* Diagnostics */}
      {state.selectedVersion?.diagnostics.errors.length ? (
        <div
          style={{
            marginTop: "0.55rem",
            padding: "0.55rem",
            border: "1px solid rgba(248,113,113,0.32)",
            borderRadius: "var(--ds-radius-md)",
            background: "rgba(127,29,29,0.15)",
            fontSize: "var(--ds-text-xs)",
            color: "#fca5a5",
          }}
        >
          {state.selectedVersion.diagnostics.errors.map((item) => (
            <div key={`${item.field}-${item.message}`}>
              <strong>{item.field}:</strong> {item.message}
            </div>
          ))}
        </div>
      ) : null}
      {state.selectedVersion?.diagnostics.warnings.length ? (
        <div
          style={{
            marginTop: "0.55rem",
            padding: "0.55rem",
            border: "1px solid rgba(245,158,11,0.32)",
            borderRadius: "var(--ds-radius-md)",
            background: "rgba(254,243,199,0.1)",
            fontSize: "var(--ds-text-xs)",
            color: "#fbbf24",
          }}
        >
          {state.selectedVersion.diagnostics.warnings.map((item) => (
            <div key={`${item.field}-${item.message}`}>
              <strong>{item.field}:</strong> {item.message}
            </div>
          ))}
        </div>
      ) : null}
    </FormSection>
  );
}
