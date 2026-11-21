// The toolbar of the Office preview: mode title and description, inspector tabs, Open PDF and the details toggle.
import type { Dispatch, SetStateAction } from "react";
import type { ToolArtifact } from "../chatThreadTypes";
import { officeRenderedPdfUrl, type OfficeInspectMode } from "./artifactPreviewUtils";
import { OfficeModeTabs } from "./artifactPreviewOfficePanels";

export function OfficeToolbar({
  artifact,
  showToolbarCopy,
  modeTitle,
  modeDescription,
  mode,
  setMode,
  detectedFileType,
  showInspector,
  setShowInspector,
}: {
  artifact: ToolArtifact;
  showToolbarCopy: boolean;
  modeTitle: string;
  modeDescription: string;
  mode: OfficeInspectMode;
  setMode: (next: OfficeInspectMode) => void;
  detectedFileType: string;
  showInspector: boolean;
  setShowInspector: Dispatch<SetStateAction<boolean>>;
}) {
  return (
    <div className="artifact-preview__office-toolbar">
      {showToolbarCopy ? (
        <div className="artifact-preview__office-toolbar-copy">
          <div className="artifact-preview__office-toolbar-title">
            {modeTitle}
          </div>
          <div className="artifact-preview__office-toolbar-description">
            {modeDescription}
          </div>
        </div>
      ) : null}
      <div className="artifact-preview__office-toolbar-controls">
        <OfficeModeTabs
          mode={mode}
          onChange={setMode}
          fileType={detectedFileType}
        />
        <a
          className="admin-panel__action-btn"
          href={officeRenderedPdfUrl(artifact)}
          target="_blank"
          rel="noopener noreferrer"
        >
          Open PDF
        </a>
        <button
          type="button"
          className="admin-panel__action-btn"
          aria-pressed={showInspector}
          onClick={() => setShowInspector((value) => !value)}
        >
          {showInspector ? "Hide details" : "Details"}
        </button>
      </div>
    </div>
  );
}
