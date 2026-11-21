// Profile drawer section listing a profile's templates of one Office document type.
import type { RefObject } from "react";
import type { useAdminCorpIdentity } from "../../hooks/useAdminCorpIdentity";
import type { AdminCorpIdentityProfile, OfficeTemplateEntry, OfficeTemplateType } from "../../types/adminPanelTypes.runtimeCorp";
import { DocTypeIcon } from "./corpIdentityIcons";
import { DOC_TYPE_LABELS, TemplateCard } from "./CorpTemplateCard";

type CorpIdentityState = ReturnType<typeof useAdminCorpIdentity>;

/** The profile's templates of one type, each with the profile detail's description when it has one. */
function CorpTemplateList({ templates, detailTemplates, state }: {
  templates: OfficeTemplateEntry[];
  detailTemplates: OfficeTemplateEntry[];
  state: CorpIdentityState;
}) {
  return (
    <div className="corp-template-list">
      {templates.map((tpl) => {
        const detailEntry = detailTemplates.find(
          (d) => d.template_id === tpl.template_id,
        );
        const effectiveDesc =
          detailEntry?.description || tpl.description || "";
        return (
          <TemplateCard
            key={tpl.template_id}
            template={{
              ...tpl,
              description: effectiveDesc,
            }}
            isBusy={
              state.corpIdentityActionBusy ===
                `update:${tpl.template_id}` ||
              state.corpIdentityActionBusy ===
                `delete-tpl:${tpl.template_id}`
            }
            onUpdate={(updates) =>
              void state.handleUpdateTemplate(
                state.corpIdentitySelectedId!,
                tpl.template_id,
                updates,
              )
            }
            onDelete={() =>
              void state.handleDeleteTemplate(
                state.corpIdentitySelectedId!,
                tpl.template_id,
                tpl.display_name || tpl.source_file_name,
              )
            }
          />
        );
      })}
    </div>
  );
}

/** "Choose a … file": opens the hidden merge file input, or cancels adding. */
function CorpTemplateAddPrompt({ docType, state, mergeInputRef, setAddingTemplateTo }: {
  docType: OfficeTemplateType;
  state: CorpIdentityState;
  mergeInputRef: RefObject<HTMLInputElement | null>;
  setAddingTemplateTo: (profileId: string | null) => void;
}) {
  return (
    <div className="corp-panel corp-panel--spaced">
      <div className="corp-panel__prompt">
        Choose a {DOC_TYPE_LABELS[docType]} file:
      </div>
      <div className="corp-row">
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary corp-btn-xs"
          onClick={() => mergeInputRef.current?.click()}
          disabled={state.corpIdentityUploadBusy}
        >
          {state.corpIdentityUploadBusy ? "Uploading…" : "Choose File"}
        </button>
        <button
          type="button"
          className="admin-panel__action-btn corp-btn-xs"
          onClick={() => setAddingTemplateTo(null)}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

export function CorpTemplateSection({
  docType,
  profile,
  state,
  addingTemplateTo,
  setAddingTemplateTo,
  mergeInputRef,
}: {
  docType: OfficeTemplateType;
  profile: AdminCorpIdentityProfile;
  state: CorpIdentityState;
  addingTemplateTo: string | null;
  setAddingTemplateTo: (profileId: string | null) => void;
  mergeInputRef: RefObject<HTMLInputElement | null>;
}) {
  const templates =
    ((profile.templates || {})[docType] as OfficeTemplateEntry[]) || [];
  const detailTemplates =
    ((state.corpIdentityDetail?.templates || {})[
      docType
    ] as OfficeTemplateEntry[]) || [];
  const isAdding = addingTemplateTo === profile.id;
  return (
    <section className="user-edit-panel__section">
      <p className="user-edit-panel__section-label">
        <span className="corp-inline-label">
          <DocTypeIcon type={docType} />
          {DOC_TYPE_LABELS[docType]} ({templates.length})
        </span>
      </p>

      {templates.length === 0 && !isAdding ? (
        <div className="corp-template-empty">
          No {DOC_TYPE_LABELS[docType]} template yet.
        </div>
      ) : (
        <CorpTemplateList templates={templates} detailTemplates={detailTemplates} state={state} />
      )}

      {isAdding && (
        <CorpTemplateAddPrompt docType={docType} state={state} mergeInputRef={mergeInputRef}
          setAddingTemplateTo={setAddingTemplateTo} />
      )}

      {!isAdding && (
        <button
          type="button"
          className="admin-panel__action-btn corp-btn-xs"
          onClick={() => setAddingTemplateTo(profile.id)}
        >
          + Add {DOC_TYPE_LABELS[docType]} Template
        </button>
      )}
    </section>
  );
}
