// The research profile side panels: creating a profile and editing one (metrics, version, policy spec and notes).
import type { FormEvent } from "react";
import type { useAdminResearchPolicies } from "../hooks/useAdminResearchPolicies";
import { ResearchPolicyStructuredEditor } from "./researchPolicies/ResearchPolicyStructuredEditor";
import { ResearchProfileMetrics } from "./researchPolicies/ResearchProfileMetrics";
import { ResearchProfileVersionSection } from "./researchPolicies/ResearchProfileVersionSection";
import { FormSection } from "../../layout/FormSection";
import { SidePanel } from "../../layout/SidePanel";
import type { ResearchPolicyProfile } from "../types/researchPolicyTypes";

type ResearchPoliciesState = ReturnType<typeof useAdminResearchPolicies>;

// Create flow: a side panel over the dimmed list, Cancel + Create at the bottom right.
export function ResearchProfileCreatePanel({ state, onCreate }: { state: ResearchPoliciesState; onCreate: (e?: FormEvent) => void }) {
  return (
    <SidePanel
      title="New research profile"
      onClose={() => state.setShowCreateProfile(false)}
      testId="research-profile-create"
      footer={
        <>
          <button type="button" className="admin-panel__action-btn" onClick={() => state.setShowCreateProfile(false)}>
            Cancel
          </button>
          <button
            type="button"
            className="admin-panel__action-btn admin-panel__action-btn--primary"
            disabled={state.saving || !state.newProfileKey.trim()}
            onClick={() => onCreate()}
          >
            {state.saving ? "Creating…" : "Create profile"}
          </button>
        </>
      }
    >
      {state.error ? <div className="admin-panel__error" role="alert">{state.error}</div> : null}
      <form onSubmit={onCreate}>
        <FormSection title="Profile">
          <label className="admin-panel__field">
            <span>Key</span>
            <input
              className="admin-panel__input"
              placeholder="e.g. custom-deep-research"
              value={state.newProfileKey}
              onChange={(e) => state.setNewProfileKey(e.target.value)}
            />
          </label>
          <label className="admin-panel__field">
            <span>Name</span>
            <input
              className="admin-panel__input"
              placeholder="Defaults to the key"
              value={state.newProfileName}
              onChange={(e) => state.setNewProfileName(e.target.value)}
            />
          </label>
          <label className="admin-panel__checkbox">
            <input
              type="checkbox"
              checked={state.createAsPublished}
              onChange={(e) => state.setCreateAsPublished(e.target.checked)}
            />
            Publish initial version
          </label>
        </FormSection>
      </form>
    </SidePanel>
  );
}

// The policy spec: the structured editor and, folded, the same draft as raw Schema JSON.
function ResearchPolicySpecSection({ state }: { state: ResearchPoliciesState }) {
  return (
    <FormSection title="Policy spec">
      <ResearchPolicyStructuredEditor
        specDraft={state.specDraft}
        onSpecDraftChange={state.setSpecDraft}
      />
      <details style={{ marginTop: "0.6rem" }}>
        <summary
          style={{
            cursor: "pointer",
            color: "var(--muted-strong)",
            fontSize: "var(--ds-text-xs)",
          }}
        >
          Schema JSON
        </summary>
        <textarea
          className="admin-panel__textarea"
          value={state.specDraft}
          onChange={(e) => state.setSpecDraft(e.target.value)}
          spellCheck={false}
          style={{
            marginTop: "0.4rem",
            minHeight: "8rem",
            fontFamily: "var(--mono-font, monospace)",
            fontSize: "var(--ds-text-xs)",
          }}
        />
      </details>
    </FormSection>
  );
}

function ResearchProfileEditFooter({ state, onClose }: { state: ResearchPoliciesState; onClose: () => void }) {
  return (
    <>
      <button type="button" className="admin-panel__action-btn" onClick={onClose}>
        Cancel
      </button>
      <button
        type="button"
        className="admin-panel__action-btn"
        disabled={state.saving || !state.selectedProfile}
        onClick={() => void state.createVersion("draft")}
      >
        {state.saving ? "Saving…" : "Save as draft"}
      </button>
      <button
        type="button"
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        disabled={state.saving || !state.selectedProfile}
        onClick={() => void state.createVersion("published")}
      >
        Create published
      </button>
    </>
  );
}

export function ResearchProfileEditPanel({ state, profile, selectedSpec, onClose }: {
  state: ResearchPoliciesState;
  profile: ResearchPolicyProfile;
  selectedSpec: Parameters<typeof ResearchProfileMetrics>[0]["spec"];
  onClose: () => void;
}) {
  return (
    <SidePanel
      title={profile.name}
      subtitle={`Research profile · ${profile.key}`}
      onClose={onClose}
      testId="research-profile-panel"
      footer={<ResearchProfileEditFooter state={state} onClose={onClose} />}
    >
      <div className="research-profile-panel">
        <FormSection title="Metrics">
          <ResearchProfileMetrics spec={selectedSpec} />
        </FormSection>

        {/* Version selector */}
        <ResearchProfileVersionSection state={state} />

        {/* Editor */}
        <ResearchPolicySpecSection state={state} />

        {/* Notes of the next version; Save as draft and Create published sit in the footer. */}
        <FormSection title="Version notes">
          <textarea
            className="admin-panel__textarea"
            value={state.newVersionNotes}
            onChange={(e) => state.setNewVersionNotes(e.target.value)}
            placeholder="What changed in this version?"
            style={{ minHeight: "3.5rem" }}
          />
        </FormSection>
      </div>
    </SidePanel>
  );
}
