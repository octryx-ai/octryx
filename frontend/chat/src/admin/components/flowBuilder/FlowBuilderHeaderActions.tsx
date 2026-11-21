import { ActionMenu } from "../workflowSurfaces/ActionMenu";

type EditorActionsProps = {
  busy: boolean;
  runBusy: boolean;
  hasFlow: boolean;
  dirty: boolean;
  runnable: boolean;
  publishReady: boolean;
  operationsOpen: boolean;
  detailsOpen: boolean;
  onBack: () => void;
  onRun: () => void;
  onToggleResults: () => void;
  onToggleDetails: () => void;
  onValidate: () => void;
  onCreateDraft: () => void;
  onPublish: () => void;
  onVersions: () => void;
  // The prompt editor with this workflow's run texts (null: no saved workflow yet).
  textsHref?: string | null;
};

// Editor header: back to the Workflows page, routine checks, one primary action (save the draft), and the panel
// toggles grouped under "More". Design-system buttons; on a narrow screen they wrap below the title, so every
// action stays reachable (no horizontal overflow at 390px).
export function FlowBuilderEditorActions({
  busy,
  runBusy,
  hasFlow,
  dirty,
  runnable,
  publishReady,
  operationsOpen,
  detailsOpen,
  onBack,
  onRun,
  onToggleResults,
  onToggleDetails,
  onValidate,
  onCreateDraft,
  onPublish,
  onVersions,
  textsHref = null,
}: EditorActionsProps) {
  return (
    <>
      <button type="button" className="admin-panel__action-btn flow-builder__back" onClick={onBack} disabled={busy}>
        ← All workflows
      </button>
      <ActionMenu
        items={[
          { label: "Results panel", onSelect: onToggleResults, disabled: !hasFlow, checked: operationsOpen },
          { label: "Details panel", onSelect: onToggleDetails, checked: detailsOpen },
          { label: "Versions", onSelect: onVersions, disabled: !hasFlow },
          {
            label: "Texts of this workflow",
            onSelect: () => {
              // A new tab: unsaved edits of this workflow stay where they are.
              if (textsHref) window.open(textsHref, "_blank", "noopener");
            },
            disabled: !textsHref,
            testId: "flow-texts-link",
          },
        ]}
      />
      <button type="button" className="admin-panel__action-btn" onClick={onValidate} disabled={busy}>
        Validate
      </button>
      {/* Opens Run & results with the input ready; only "Run this revision" there starts a run. */}
      <button type="button" className="admin-panel__action-btn" onClick={onRun} disabled={busy || !runnable}
        title="Open Run & results to set the input and run this revision">
        {runBusy ? "Running…" : "Run…"}
      </button>
      <button type="button" className="admin-panel__action-btn" onClick={onPublish} disabled={busy || !publishReady}>
        Publish
      </button>
      <button
        type="button"
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        onClick={onCreateDraft}
        disabled={busy || (hasFlow && !dirty)}
      >
        {hasFlow ? "Save draft" : "Create draft"}
      </button>
    </>
  );
}
