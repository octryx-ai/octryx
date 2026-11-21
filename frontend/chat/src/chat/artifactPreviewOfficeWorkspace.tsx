// The Office artifact preview: rendered document, inspector modes, details sidecar and suggested actions.
import { useEffect, useMemo } from "react";
import type { ToolArtifact } from "../chatThreadTypes";
import {
  officePreviewUrl,
  type OfficeInspectMode,
  type OfficeInspectPayload,
} from "./artifactPreviewUtils";
import { OfficeContentPanel } from "./artifactPreviewOfficePanels";
import { OfficeDetailsSidecar } from "./artifactPreviewOfficeSidecar";
import {
  draftOfficeAction,
  officeModeView,
  useOfficeInspectState,
  useOfficeRenderedPreview,
} from "./artifactPreviewOfficeState";
import { OfficeToolbar } from "./artifactPreviewOfficeToolbar";

type OfficeStageProps = {
  artifact: ToolArtifact;
  previewState: "loading" | "ready" | "error";
  previewHtml: string;
  payload: OfficeInspectPayload | null;
  mode: OfficeInspectMode;
  error: string;
};

function OfficeStage({ artifact, previewState, previewHtml, payload, mode, error }: OfficeStageProps) {
  return (
    <section className="artifact-preview__office-stage">
      <div className="artifact-preview__office-stage-surface">
        {mode === "html" ? (
          previewState === "error" ? (
            <div className="artifact-preview__empty artifact-preview__empty--office">
              <div>
                <div className="artifact-preview__empty-title">
                  Preview unavailable
                </div>
                <div className="artifact-preview__empty-copy">
                  The document could not be read for a preview. Use the
                  inspector tabs for the structured view, or open the file
                  directly in a new tab.
                </div>
              </div>
            </div>
          ) : (
            <iframe
              className="artifact-preview__frame artifact-preview__frame--office"
              srcDoc={previewHtml}
              title={artifact.name}
              // Generated content: an opaque origin, never the platform's (no allow-same-origin).
              sandbox="allow-scripts"
            />
          )
        ) : (
          <OfficeContentPanel payload={payload} mode={mode} error={error} />
        )}
      </div>
    </section>
  );
}

type OfficeWorkspaceProps = {
  artifact: ToolArtifact;
};

export function OfficeWorkspace({ artifact }: OfficeWorkspaceProps) {
  const office = useOfficeInspectState(artifact);
  const { mode, actionMode, payload, showInspector, setShowInspector } = office;
  const modeView = officeModeView(artifact, mode, actionMode, payload);
  const { isRenderedPreview, modeTitle, detectedFileType } = modeView;
  const actions = office.actionsPayload?.actions ?? [];
  const officePreviewHref = useMemo(() => officePreviewUrl(artifact), [artifact]);

  useEffect(() => {
    setShowInspector(!isRenderedPreview);
  }, [isRenderedPreview, setShowInspector]);

  const { setBusyActionId, setActionsError } = office;
  const draftAction = (actionId: string) =>
    draftOfficeAction({ artifact, actionId, actionMode, setBusyActionId, setActionsError });
  const previewState = useOfficeRenderedPreview(artifact.path, isRenderedPreview, officePreviewHref, office.setPreviewHtml, setShowInspector);

  return (
    <div className="artifact-preview__office-shell">
      <OfficeToolbar
        artifact={artifact}
        showToolbarCopy={modeView.showToolbarCopy}
        modeTitle={modeTitle}
        modeDescription={modeView.modeDescription}
        mode={mode}
        setMode={office.setMode}
        detectedFileType={detectedFileType}
        showInspector={showInspector}
        setShowInspector={setShowInspector}
      />
      <div
        className={`artifact-preview__office-layout${showInspector ? "" : " artifact-preview__office-layout--focus"}`}
      >
        <OfficeStage artifact={artifact} previewState={previewState} previewHtml={office.previewHtml} payload={payload} mode={mode} error={office.error} />
        {showInspector ? (
          <OfficeDetailsSidecar
            artifact={artifact}
            detectedFileType={detectedFileType}
            isRenderedPreview={isRenderedPreview}
            modeTitle={modeTitle}
            summaryRows={office.summaryRows}
            actions={actions}
            actionMode={actionMode}
            setActionMode={office.setActionMode}
            actionModeDescription={modeView.actionModeDescription}
            actionsError={office.actionsError}
            busyActionId={office.busyActionId}
            draftOfficeAction={draftAction}
          />
        ) : null}
      </div>
    </div>
  );
}
