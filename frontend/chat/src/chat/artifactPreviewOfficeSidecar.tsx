// The details sidecar of the Office preview: document type, mode, profile, path, quick summary and suggested actions.
import type { ToolArtifact } from "../chatThreadTypes";
import {
  formatOfficeValue,
  officeTypeHint,
  titleFromKey,
  type OfficeActionMode,
  type OfficeActionsPayload,
} from "./artifactPreviewUtils";
import { OfficeActionModeToggle } from "./artifactPreviewOfficePanels";

function OfficeSummaryCard({ summaryRows }: { summaryRows: Array<[string, unknown]> }) {
  return (
    <div className="artifact-preview__sidecard">
      <div className="artifact-preview__sidecard-label">
        Quick summary
      </div>
      <div className="artifact-preview__stat-list">
        {summaryRows.map(([key, value]) => (
          <div key={key} className="artifact-preview__stat-row">
            <span className="artifact-preview__stat-key">
              {titleFromKey(key)}
            </span>
            <span className="artifact-preview__stat-value">
              {formatOfficeValue(value)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

type OfficeActionsCardProps = {
  actions: OfficeActionsPayload["actions"];
  actionMode: OfficeActionMode;
  setActionMode: (next: OfficeActionMode) => void;
  actionModeDescription: string;
  actionsError: string;
  busyActionId: string | null;
  // Resolves the action into a draft in the composer; nothing runs until the person sends it.
  draftOfficeAction: (actionId: string) => Promise<void>;
};

function OfficeActionItem({ action, busy, draft }: {
  action: OfficeActionsPayload["actions"][number];
  busy: boolean;
  draft: OfficeActionsCardProps["draftOfficeAction"];
}) {
  return (
    <div className="artifact-preview__action-item">
      <div className="artifact-preview__action-copy">
        <strong>{action.label}</strong>
        <span>{action.description}</span>
      </div>
      <div className="artifact-preview__action-buttons">
        <button
          type="button"
          className="plain-button"
          disabled={busy}
          onClick={() => void draft(action.id)}
        >
          Use as draft
        </button>
      </div>
    </div>
  );
}

function OfficeActionsCard({
  actions,
  actionMode,
  setActionMode,
  actionModeDescription,
  actionsError,
  busyActionId,
  draftOfficeAction,
}: OfficeActionsCardProps) {
  return (
    <div className="artifact-preview__sidecard">
      <div className="artifact-preview__sidecard-label">
        Suggested actions
      </div>
      <OfficeActionModeToggle
        value={actionMode}
        onChange={setActionMode}
      />
      <div className="artifact-preview__sidecard-copy">
        {actionModeDescription}
      </div>
      {actionsError ? (
        <div className="artifact-preview__sidecard-copy">
          {actionsError}
        </div>
      ) : null}
      <div className="artifact-preview__action-list">
        {actions.map((action) => (
          <OfficeActionItem key={action.id} action={action} busy={busyActionId === action.id} draft={draftOfficeAction} />
        ))}
      </div>
    </div>
  );
}

export function OfficeDetailsSidecar({
  artifact,
  detectedFileType,
  isRenderedPreview,
  modeTitle,
  summaryRows,
  ...actionProps
}: {
  artifact: ToolArtifact;
  detectedFileType: string;
  isRenderedPreview: boolean;
  modeTitle: string;
  summaryRows: Array<[string, unknown]>;
} & OfficeActionsCardProps) {
  return (
    <aside className="artifact-preview__sidecar artifact-preview__sidecar--office">
      <div className="artifact-preview__sidecard">
        <div className="artifact-preview__sidecard-label">
          Document type
        </div>
        <div className="artifact-preview__sidecard-value">
          {detectedFileType.toUpperCase()}
        </div>
      </div>
      <div className="artifact-preview__sidecard">
        <div className="artifact-preview__sidecard-label">
          Current mode
        </div>
        <div className="artifact-preview__sidecard-value">
          {isRenderedPreview ? "Preview" : modeTitle}
        </div>
      </div>
      <div className="artifact-preview__sidecard">
        <div className="artifact-preview__sidecard-label">
          Document profile
        </div>
        <div className="artifact-preview__sidecard-copy">
          {officeTypeHint(detectedFileType)}
        </div>
      </div>
      <div className="artifact-preview__sidecard">
        <div className="artifact-preview__sidecard-label">
          Output path
        </div>
        <div className="artifact-preview__sidecard-path">
          {artifact.path}
        </div>
      </div>
      {summaryRows.length ? <OfficeSummaryCard summaryRows={summaryRows} /> : null}
      {actionProps.actions.length ? <OfficeActionsCard {...actionProps} /> : null}
    </aside>
  );
}
