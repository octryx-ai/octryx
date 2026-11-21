import { useState, type ReactNode } from "react";

import { OptionsIcon } from "./composerIcons";
import { ComposerAttachButton } from "./composer/ComposerUtilityActions";
import { useComposerFooterParts } from "./composerFooterParts";
import type { ChatLayoutMode } from "./responsive/chatLayoutBreakpoints";
import type { ComposerShellProps } from "./composerShellTypes";

const COMPACT_OPTIONS_PANEL_ID = "composer-compact-options";

export type ComposerFooterControlsProps = Pick<
  ComposerShellProps,
  | "composerDisabled"
  | "uploadingAttachments"
  | "fileInputRef"
  | "runtimePillLabel"
  | "selectedRuntimeTargetId"
  | "setSelectedRuntimeTargetId"
  | "runtimeOptions"
  | "projectPillLabel"
  | "selectedProjectId"
  | "selectedThinkingLevel"
  | "setSelectedThinkingLevel"
  | "workflowOptions"
  | "selectedWorkflowKey"
  | "setSelectedWorkflowKey"
  | "workflowPillLabel"
  | "selectedWorkflowCapability"
  | "sttAvailable"
  | "sttListening"
  | "startSTT"
  | "selectedSession"
  | "showCanvas"
  | "openCanvas"
  | "ttsEnabled"
  | "selectedSessionIsRunning"
  | "selectedSessionIsArchived"
  | "sending"
  | "composerValue"
  | "draftAttachments"
  | "textareaRef"
  | "handleComposerChange"
  | "handleStop"
  | "handleSend"
> & {
  layoutMode: ChatLayoutMode;
};

type FooterParts = ReturnType<typeof useComposerFooterParts> & { runStatus: ReactNode };

export function ComposerFooterControls(props: ComposerFooterControlsProps) {
  const { layoutMode, composerDisabled, uploadingAttachments, fileInputRef, ttsEnabled, selectedSessionIsRunning } = props;
  // The disclosure stays open across a layout switch, so its state lives here.
  const [compactOptionsOpen, setCompactOptionsOpen] = useState(false);
  const compactComposer = layoutMode === "phone";
  const parts = useComposerFooterParts(props);

  // The audit lock sits in the chat header; the footer only adds an active run.
  const runStatus = selectedSessionIsRunning ? <span className="composer__hint-text">Run active</span> : null;

  if (compactComposer) {
    return (
      <ComposerFooterCompact
        {...parts}
        runStatus={runStatus}
        attach={{ composerDisabled, uploadingAttachments, fileInputRef }}
        compactOptionsOpen={compactOptionsOpen}
        setCompactOptionsOpen={setCompactOptionsOpen}
      />
    );
  }

  return <ComposerFooterWide {...parts} runStatus={runStatus} ttsEnabled={ttsEnabled} />;
}

// Phone composer: message entry, attach and send/stop stay visible;
// routing and utility controls move behind one labelled disclosure. The
// selected route stays readable in the workspace header chips.
function ComposerFooterCompact({
  routingPills,
  utilityActions,
  submitButton,
  runStatus,
  attach,
  compactOptionsOpen,
  setCompactOptionsOpen,
}: FooterParts & {
  attach: Pick<ComposerFooterControlsProps, "composerDisabled" | "uploadingAttachments" | "fileInputRef">;
  compactOptionsOpen: boolean;
  setCompactOptionsOpen: (update: (current: boolean) => boolean) => void;
}) {
  return (
    <div className="composer__footer composer__footer--compact">
      <div className="composer__controls-shell">
        <div className="composer__toolbar composer__toolbar--primary">
          <ComposerAttachButton
            composerDisabled={attach.composerDisabled}
            uploadingAttachments={attach.uploadingAttachments}
            fileInputRef={attach.fileInputRef}
          />
          <button
            type="button"
            className={`composer-action-button composer-action-button--options ${compactOptionsOpen ? "composer-action-button--active" : ""}`}
            aria-expanded={compactOptionsOpen}
            aria-controls={COMPACT_OPTIONS_PANEL_ID}
            onClick={() => setCompactOptionsOpen((current) => !current)}
          >
            <OptionsIcon />
            <span>Options</span>
          </button>
          {submitButton}
        </div>
        {compactOptionsOpen ? (
          <div
            id={COMPACT_OPTIONS_PANEL_ID}
            className="composer__compact-options"
          >
            {routingPills}
            {utilityActions(false)}
          </div>
        ) : null}
        {runStatus ? (
          <div className="composer__hint-row" aria-hidden="true">
            <div className="composer__hint-group composer__hint-group--status">
              {runStatus}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ComposerFooterWide({
  routingPills,
  utilityActions,
  submitButton,
  runStatus,
  ttsEnabled,
}: FooterParts & { ttsEnabled: boolean }) {
  return (
    <div className="composer__footer">
      <div className="composer__controls-shell">
        <div className="composer__toolbar composer__toolbar--primary">
          {routingPills}
          <div className="composer__toolbar-spacer" />
          {utilityActions(true)}
          {submitButton}
        </div>
        {/* The keyboard hints live in the chat help; only a live state shows here. */}
        {ttsEnabled || runStatus ? (
          <div className="composer__hint-row" aria-hidden="true">
            <div className="composer__hint-group composer__hint-group--status">
              {ttsEnabled ? <span className="composer__hint-text">Voice enabled</span> : null}
              {ttsEnabled && runStatus ? <span className="composer__hint-separator">·</span> : null}
              {runStatus}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
