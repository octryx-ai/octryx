// Top bar of a phased workflow: back link, title and status, texts link, Edit as draft and Publish.
import { promptTextsHref } from "../../../editorLinks";
import { StatusLabel } from "../../../../layout/StatusLabel";
import { designerStatus, phasedStatusLabel, type PhasedView } from "./phasedWorkflowModel";

type Props = {
  view: PhasedView;
  busy: boolean;
  blocked: string | null;
  onBack?: () => void;
  onEditAsDraft: () => void;
  onPublish: () => void;
};

export function PhasedEditorHeader({ view, busy, blocked, onBack, onEditAsDraft, onPublish }: Props) {
  return (
  <div className="flow-builder__topbar">
    {onBack ? (
      <button type="button" className="admin-panel__action-btn flow-builder__back" onClick={onBack}>← All workflows</button>
    ) : null}
    <div className="flow-builder__title-block">
      <span className="admin-panel__eyebrow">
        Workflow · Runs in phases
      </span>
      <div className="flow-builder__title-row">
        <h2 title={view.title || view.key}>{view.title || view.key}</h2>
        <span data-testid="designer-status" data-status={designerStatus(view)}>
          <StatusLabel label={phasedStatusLabel(view)} tone={view.status === "published" ? "neutral" : "attention"} />
        </span>
      </div>
    </div>
    <div className="flow-builder__header-actions">
      {/* The run texts this workflow's runs get, in the prompt editor with this workflow's scope. A new tab:
          unsaved edits here stay. */}
      <a className="admin-panel__action-btn" href={promptTextsHref(`workflow:${view.key}`)} target="_blank"
        rel="noopener" data-testid="designer-texts-link" title="The texts this workflow's runs send their agent">
        Texts of this workflow
      </a>
      {view.editable && (view.composite || view.version_status !== "draft") && view.definition ? (
        <button type="button" className="admin-panel__action-btn" data-testid="designer-edit-draft" disabled={busy}
          title={view.composite
            ? "Make an editable draft of this workflow; it stops following its building blocks. Runs keep using this version until you publish"
            : "Make a draft of this version to change it; runs keep using this one until you publish"}
          onClick={onEditAsDraft}>Edit as draft</button>
      ) : null}
      {view.editable ? (
        <>
          {blocked ? (
            <span className="admin-panel__hint aw-publish-reason" data-testid="phased-publish-reason" title={blocked}>{blocked}</span>
          ) : null}
          <button
            type="button"
            className="admin-panel__action-btn admin-panel__action-btn--primary"
            disabled={Boolean(blocked) || busy}
            title={blocked || "Make this version the one new runs use"}
            onClick={onPublish}
          >
            Publish
          </button>
        </>
      ) : null}
    </div>
  </div>
  );
}
