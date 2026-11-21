import { type ChangeEvent, useCallback, useMemo, useRef, useState } from "react";
import { CorpProfileDrawer } from "./corpIdentity/CorpProfileDrawer";
import { CorpProfilesTable } from "./corpIdentity/CorpProfilesTable";
import { RefreshIcon, UploadIcon } from "./corpIdentity/corpIdentityIcons";
import "./corpIdentity/corpIdentity.css";
import { AdminPresentationFallbackSection } from "./AdminPresentationFallbackSection";
import { readJson } from "../utils/adminPanelHelpers";
import { useAdminCorpIdentity } from "../hooks/useAdminCorpIdentity";
import type { ProjectOption } from "../../chatOptionTypes";
import { EmptyLine } from "../../layout/EmptyLine";
import { FormSection } from "../../layout/FormSection";
import { SidePanel } from "../../layout/SidePanel";

const TEMPLATE_TYPES = ".potx,.pptx,.dotx,.docx,.xltx,.xlsx";

// "New profile from template": a side panel over the dimmed list with one labelled file field and
// Cancel + Create at the bottom right; the upload is the same call.
function NewCorpProfilePanel({ busy, onCreate, onClose }: { busy: boolean; onCreate: (file: File) => void; onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  return (
    <SidePanel title="New corporate identity profile" onClose={onClose} testId="corp-new-profile-panel"
      footer={(
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onClose} data-testid="corp-new-profile-cancel">Cancel</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={!file || busy}
            onClick={() => { if (file) onCreate(file); }} data-testid="corp-new-profile-create">
            {busy ? "Creating…" : "Create profile"}
          </button>
        </>
      )}
    >
      <FormSection title="Template">
        <label className="admin-panel__field">
          <span>Template file (PPTX, DOCX or XLSX)</span>
          <input type="file" accept={TEMPLATE_TYPES} data-testid="corp-new-profile-file"
            onChange={(event: ChangeEvent<HTMLInputElement>) => setFile(event.target.files?.[0] ?? null)} />
        </label>
      </FormSection>
    </SidePanel>
  );
}

type AdminCorpIdentityTabProps = {
  projects: ProjectOption[];
};

/** The page state: the profiles hook, the add-template target, the new-profile panel and the merge upload. */
function useCorpIdentityPage() {
  const state = useAdminCorpIdentity({ readJson });

  const [addingTemplateTo, setAddingTemplateTo] = useState<string | null>(null);
  const [showNewProfile, setShowNewProfile] = useState(false);

  const mergeInputRef = useRef<HTMLInputElement>(null);

  const createProfile = useCallback(
    (file: File) => {
      void state.handleUploadCorpIdentity(file, null);
      setShowNewProfile(false);
    },
    [state],
  );

  const handleMergeFileChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file && addingTemplateTo) {
        void state.handleUploadCorpIdentity(file, addingTemplateTo);
        e.target.value = "";
        setAddingTemplateTo(null);
      }
    },
    [state, addingTemplateTo],
  );

  const selectedProfile = useMemo(
    () =>
      state.corpIdentityProfiles.find(
        (p) => p.id === state.corpIdentitySelectedId,
      ) || null,
    [state.corpIdentityProfiles, state.corpIdentitySelectedId],
  );

  const handleCloseDrawer = useCallback(() => {
    void state.loadCorpIdentityDetail(null);
    setAddingTemplateTo(null);
  }, [state]);

  return {
    state, addingTemplateTo, setAddingTemplateTo, showNewProfile, setShowNewProfile, mergeInputRef, createProfile,
    handleMergeFileChange, selectedProfile, handleCloseDrawer,
  };
}

/** The profile count with Refresh and "New profile from template". */
function CorpIdentityHeader({ count, onRefresh, onNewProfile }: { count: number; onRefresh: () => void; onNewProfile: () => void }) {
  return (
    <div className="corp-header">
      <span className="corp-header__title">
        Profiles ({count})
      </span>
      <div className="corp-header__actions">
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={onRefresh}
        >
          <RefreshIcon />
          Refresh
        </button>
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={onNewProfile}
          data-testid="corp-new-profile"
        >
          <UploadIcon />
          + New profile from template
        </button>
      </div>
    </div>
  );
}

export function AdminCorpIdentityTab({ projects }: AdminCorpIdentityTabProps) {
  const {
    state, addingTemplateTo, setAddingTemplateTo, showNewProfile, setShowNewProfile, mergeInputRef, createProfile,
    handleMergeFileChange, selectedProfile, handleCloseDrawer,
  } = useCorpIdentityPage();

  return (
    <div className="admin-users">
      <p className="admin-panel__hint" data-testid="corp-purpose">Used for generated documents and as the default look of the products specified in Spec Studio. Octryx's own look: Branding.</p>
      <AdminPresentationFallbackSection />
      {state.corpIdentityError ? <p role="alert">{state.corpIdentityError}</p> : null}
      {/* Hidden inputs */}
      <input
        ref={mergeInputRef}
        id="corp-identity-merge-file-input"
        type="file"
        accept={TEMPLATE_TYPES}
        className="corp-hidden"
        onChange={handleMergeFileChange}
      />

      {/* Header */}
      <CorpIdentityHeader count={state.corpIdentityProfiles.length} onRefresh={() => void state.refreshCorpIdentities()}
        onNewProfile={() => setShowNewProfile(true)} />

      {state.corpIdentityProfiles.length === 0 ? (
        <EmptyLine text="No corporate identity profiles yet."
          action={{ label: "New profile from template", onClick: () => setShowNewProfile(true) }} testId="corp-empty" />
      ) : (
        <CorpProfilesTable state={state} />
      )}

      {showNewProfile ? (
        <NewCorpProfilePanel busy={state.corpIdentityUploadBusy} onCreate={createProfile} onClose={() => setShowNewProfile(false)} />
      ) : null}

      {/* Side drawer */}
      {state.corpIdentitySelectedId && selectedProfile ? (
        <CorpProfileDrawer
          profile={selectedProfile}
          state={state}
          addingTemplateTo={addingTemplateTo}
          setAddingTemplateTo={setAddingTemplateTo}
          mergeInputRef={mergeInputRef}
          onClose={handleCloseDrawer}
        />
      ) : null}
    </div>
  );
}
