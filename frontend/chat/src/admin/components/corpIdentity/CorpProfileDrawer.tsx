// Side drawer for one corporate identity profile: brand summary, templates per type, brand sheet, example deck, actions.
import type { RefObject } from "react";
import type { useAdminCorpIdentity } from "../../hooks/useAdminCorpIdentity";
import type { AdminCorpIdentityProfile, OfficeTemplateType } from "../../types/adminPanelTypes.runtimeCorp";
import { CorpIdentityBrandSheet } from "./CorpIdentityBrandSheet";
import { CorpStudioLocks } from "./CorpStudioLocks";
import { CorpTemplateSection } from "./CorpTemplateSection";
import { HexSwatch } from "./CorpTemplateCard";
import { CloseIcon } from "./corpIdentityIcons";

type CorpIdentityState = ReturnType<typeof useAdminCorpIdentity>;

const DOC_TYPES: OfficeTemplateType[] = ["pptx", "docx", "xlsx"];

type CorpProfileDrawerProps = {
  profile: AdminCorpIdentityProfile;
  state: CorpIdentityState;
  addingTemplateTo: string | null;
  setAddingTemplateTo: (profileId: string | null) => void;
  mergeInputRef: RefObject<HTMLInputElement | null>;
  onClose: () => void;
};

export function CorpProfileDrawer({
  profile, state, addingTemplateTo, setAddingTemplateTo, mergeInputRef, onClose,
}: CorpProfileDrawerProps) {
  const summary = state.corpIdentityDetail?.summary;
  return (
    <div
      className="user-edit-panel__backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <aside className="user-edit-panel">
        <div className="user-edit-panel__header">
          <div>
            <p className="user-edit-panel__header-label">Profile</p>
            <h2 className="user-edit-panel__header-name">
              {state.corpIdentityDetail?.name || profile.name}
            </h2>
          </div>
          <button
            type="button"
            className="user-edit-panel__close"
            onClick={onClose}
            aria-label="Close"
          >
            <CloseIcon />
          </button>
        </div>

        <div className="user-edit-panel__body">
          {/* Brand summary */}
          <CorpBrandSummary summary={summary} />

          {/* Templates per doc type */}
          {DOC_TYPES.map((docType) => (
            <CorpTemplateSection key={docType} docType={docType} profile={profile} state={state}
              addingTemplateTo={addingTemplateTo} setAddingTemplateTo={setAddingTemplateTo} mergeInputRef={mergeInputRef} />
          ))}

          {/* Corporate Identity brand sheet */}
          <CorpIdentityBrandSheet profileId={profile.id} brief={state.corpIdentityBrief} />

          {/* What a spec may not change of this look */}
          <CorpStudioLocks profileId={profile.id} locks={profile.studio_locks ?? []} />

          {/* Example deck (Slot 2) */}
          <CorpExampleDeck profile={profile} state={state} />

          {/* Profile actions */}
          <CorpProfileActions profile={profile} state={state} />
        </div>
      </aside>
    </div>
  );
}

type Summary = NonNullable<CorpIdentityState["corpIdentityDetail"]>["summary"];
type PartProps = { profile: AdminCorpIdentityProfile; state: CorpIdentityState };

function CorpBrandSummary({ summary }: { summary: Summary | undefined }) {
  return (
    <section className="user-edit-panel__section">
      <p className="user-edit-panel__section-label">Brand</p>
      <div className="corp-brand-facts">
        <div className="corp-panel">
          <span className="corp-brand-facts__label">Theme</span>
          <strong className="corp-brand-facts__value">
            {summary?.theme_name || "—"}
          </strong>
        </div>
        <div className="corp-panel">
          <span className="corp-brand-facts__label">Font</span>
          <strong className="corp-brand-facts__value">
            {summary?.font_family || "—"}
          </strong>
        </div>
      </div>
      {summary?.colors?.length ? (
        <div className="corp-color-chips">
          {summary.colors.map((color) => (
            <div key={`${color.token}-${color.hex}`} className="corp-chip">
              <HexSwatch hex={color.hex || "#666"} />
              <span className="corp-muted">{color.token}</span>
              <code className="corp-color-chips__hex">{color.hex}</code>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function CorpExampleDeck({ profile, state }: PartProps) {
  return (
    <section className="user-edit-panel__section">
      <p className="user-edit-panel__section-label">
        Example deck (Slot 2 — teaches layout usage)
      </p>
      {profile.example_deck_file ? (
        <div className="user-edit-panel__row-end corp-example-row">
          <span className="task-item__badge task-item__badge--secondary">
            {profile.example_deck_file}
            {typeof profile.example_deck_layouts_learned === "number"
              ? ` · ${profile.example_deck_layouts_learned} layouts learned`
              : ""}
          </span>
          <button
            type="button"
            className="admin-panel__danger-btn"
            disabled={
              state.corpIdentityActionBusy === `example-clear:${profile.id}`
            }
            onClick={() => void state.handleClearExampleDeck(profile.id)}
          >
            Remove
          </button>
        </div>
      ) : (
        <p className="admin-panel__hint">
          No example deck. The profile learns dramaturgy from its own
          sample slides — upload a real deck built on this brand to
          teach it how each layout is used.
        </p>
      )}
      <label className="admin-panel__action-btn corp-upload-label">
        {state.corpIdentityActionBusy === `example:${profile.id}`
          ? "Learning…"
          : profile.example_deck_file
            ? "Replace example deck"
            : "Upload example deck"}
        <input
          type="file"
          accept=".pptx,.potx"
          className="corp-hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) {
              void state.handleAttachExampleDeck(profile.id, file);
            }
            e.target.value = "";
          }}
        />
      </label>
    </section>
  );
}

function CorpProfileActions({ profile, state }: PartProps) {
  return (
    <section className="user-edit-panel__section">
      <p className="user-edit-panel__section-label">Profile</p>
      <div className="user-edit-panel__row-end">
        {!profile.is_default && (
          <button
            type="button"
            className="admin-panel__action-btn admin-panel__action-btn--primary"
            disabled={
              state.corpIdentityActionBusy ===
              `default:${state.corpIdentitySelectedId}`
            }
            onClick={() =>
              void state.handleSetDefaultCorpIdentity(
                state.corpIdentitySelectedId!,
              )
            }
          >
            Set as Default
          </button>
        )}
        <button
          type="button"
          className="admin-panel__action-btn"
          disabled={
            state.corpIdentityActionBusy ===
            `reextract:${state.corpIdentitySelectedId}`
          }
          onClick={() =>
            void state.handleReextractCorpIdentity(
              state.corpIdentitySelectedId!,
            )
          }
        >
          {state.corpIdentityActionBusy ===
          `reextract:${state.corpIdentitySelectedId}`
            ? "Re-extracting…"
            : "Re-extract Brand"}
        </button>
      </div>
    </section>
  );
}
