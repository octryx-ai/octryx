import type { SessionPullRequest, ThreadCodeIntelligenceStats, ThreadUsageStats } from "../../chatUsageTypes";
import { StatsPopover } from "../StatsPopover";
import {
  BrainIcon,
  ContinueIcon,
  ErrorIcon,
  ExportIcon,
  FolderIcon,
  StatsIcon,
  ThemeIcon,
  TraceIcon,
} from "../ChatShellIcons";
import type { ChatLayoutMode } from "../responsive/chatLayoutBreakpoints";
import { TranscriptIcon } from "../transcripts/TranscriptButton";
import type { SessionPoolItem } from "./useSessionPool";
import {
  WorkspaceHeaderOverflowMenu,
  type WorkspaceHeaderMenuItem,
} from "./WorkspaceHeaderOverflowMenu";

export type WorkspaceHeaderActionsProps = {
  layoutMode: ChatLayoutMode;
  hasSelectedSession: boolean;
  taskError: string;
  taskErrorSummary: string;
  taskErrorOpen: boolean;
  setTaskErrorOpen: (value: boolean | ((value: boolean) => boolean)) => void;
  selectedSessionIsArchived?: boolean;
  selectedSessionIsRunning: boolean;
  onContinue: () => void;
  workspaceOpen: boolean;
  onToggleWorkspace: () => void;
  onExportEvidencePdf: () => void;
  onExportAnalysisJson: () => void;
  // The holder's "Put into the session pool"; null without an open session.
  poolItem?: SessionPoolItem | null;
  chatTheme: "dark" | "light";
  setChatTheme: (
    value: "dark" | "light" | ((value: "dark" | "light") => "dark" | "light"),
  ) => void;
  statsOpen: boolean;
  setStatsOpen: (value: boolean | ((value: boolean) => boolean)) => void;
  stats: ThreadUsageStats | null;
  codeIntelligence: ThreadCodeIntelligenceStats | null;
  pullRequests: SessionPullRequest[];
  traceEventCount: number;
  onOpenTrace: () => void;
  // Opens the session's full transcript; null when none is stored or readable (then no entry is shown).
  onOpenTranscript?: (() => void) | null;
};
type Props = WorkspaceHeaderActionsProps;

function renderErrorAction({
  taskError,
  taskErrorSummary,
  taskErrorOpen,
  setTaskErrorOpen,
  selectedSessionIsArchived,
  selectedSessionIsRunning,
  onContinue,
}: Props) {
  return taskError ? (
    <div className="stats-popover-shell">
      <button
        type="button"
        className="icon-action-button icon-action-button--error"
        aria-label="Show action error"
        title={taskErrorSummary || "Show action error"}
        data-tooltip="Show action error"
        onClick={() => setTaskErrorOpen((value) => !value)}
      >
        <ErrorIcon />
      </button>
      {taskErrorOpen ? (
        <div className="stats-panel stats-panel--error">
          <div className="stats-panel__eyebrow">
            <span>Action failed</span>
          </div>
          <div className="stats-panel__error-summary">{taskErrorSummary}</div>
          <pre className="stats-panel__error-body">{taskError}</pre>
          {!selectedSessionIsArchived && !selectedSessionIsRunning ? (
            <button
              type="button"
              className="workspace__error-action"
              onClick={onContinue}
            >
              <ContinueIcon />
              <span>Retry</span>
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  ) : null;
}

// Desktop names the action next to its icon ("Trace 2"); on phones the count sits on the icon.
function renderTraceAction({ traceEventCount, onOpenTrace }: Props, labelled: boolean) {
  return (
    <button
      type="button"
      className={`icon-action-button icon-action-button--trace${labelled ? " icon-action-button--labeled" : ""}`}
      aria-label={`Open execution trace (${traceEventCount} events)`}
      data-tooltip={labelled ? undefined : "Execution trace"}
      onClick={onOpenTrace}
    >
      <TraceIcon />
      {labelled ? <span>Trace</span> : null}
      <span className={labelled ? "icon-action-button__count" : undefined}>{traceEventCount}</span>
    </button>
  );
}

function buildHandOverItems({ poolItem = null }: Props): WorkspaceHeaderMenuItem[] {
  return poolItem ? [{ key: "pool", label: poolItem.label, icon: <ExportIcon />, onSelect: poolItem.onSelect, disabled: poolItem.disabled }] : [];
}

function buildExportItems({ onExportEvidencePdf, onExportAnalysisJson, hasSelectedSession }: Props): WorkspaceHeaderMenuItem[] {
  return [
    {
      key: "export-pdf",
      label: "Export evidence PDF",
      icon: <ExportIcon />,
      onSelect: onExportEvidencePdf,
      disabled: !hasSelectedSession,
    },
    {
      key: "export-analysis",
      label: "Export analysis JSON",
      icon: <BrainIcon />,
      onSelect: onExportAnalysisJson,
      disabled: !hasSelectedSession,
    },
  ];
}

function buildPhoneOverflowItems(
  { workspaceOpen, onToggleWorkspace, onOpenTranscript = null, setStatsOpen, hasSelectedSession, statsOpen, chatTheme }: Props,
  exportItems: WorkspaceHeaderMenuItem[],
  themeActionLabel: string,
  toggleTheme: () => void,
): WorkspaceHeaderMenuItem[] {
  return [
    {
      key: "workspace",
      label: workspaceOpen ? "Hide working files" : "Open working files",
      icon: <FolderIcon />,
      onSelect: onToggleWorkspace,
      active: workspaceOpen,
    },
    ...exportItems,
    ...(onOpenTranscript
      ? [{ key: "transcript", label: "Open session transcript", icon: <TranscriptIcon />, onSelect: onOpenTranscript }]
      : []),
    {
      key: "stats",
      label: "Open chat statistics",
      icon: <StatsIcon />,
      onSelect: () => setStatsOpen((value) => !value),
      disabled: !hasSelectedSession,
      active: statsOpen,
    },
    {
      key: "theme",
      label: themeActionLabel,
      icon: <ThemeIcon theme={chatTheme} />,
      onSelect: toggleTheme,
    },
  ];
}

function renderFilesButton({ workspaceOpen, onToggleWorkspace }: Props) {
  return (
    <button
      type="button"
      className={`icon-action-button icon-action-button--labeled${workspaceOpen ? " icon-action-button--active" : ""}`}
      aria-label={workspaceOpen ? "Hide working files" : "Open working files"}
      aria-pressed={workspaceOpen}
      onClick={onToggleWorkspace}
    >
      <FolderIcon />
      <span>Files</span>
    </button>
  );
}

function renderStatsShell({ statsOpen, setStatsOpen, hasSelectedSession, stats, codeIntelligence, pullRequests }: Props) {
  return (
    <div className="stats-popover-shell">
      <button
        type="button"
        className={`icon-action-button icon-action-button--labeled${statsOpen ? " icon-action-button--active" : ""}`}
        aria-label="Open chat statistics"
        disabled={!hasSelectedSession}
        onClick={() => setStatsOpen((value) => !value)}
      >
        <StatsIcon />
        <span>Usage</span>
      </button>
      {statsOpen ? (
        <StatsPopover stats={stats} codeIntelligence={codeIntelligence} pullRequests={pullRequests} />
      ) : null}
    </div>
  );
}

function renderTranscriptButton(onOpenTranscript: (() => void) | null) {
  return onOpenTranscript ? (
    <button
      type="button"
      className="icon-action-button icon-action-button--labeled"
      aria-label="Open session transcript"
      data-testid="header-transcript"
      onClick={onOpenTranscript}
    >
      <TranscriptIcon />
      <span>Transcript</span>
    </button>
  ) : null;
}

// The workspace header action cluster. On phone widths the secondary actions
// (working files, exports, theme, statistics) collapse behind an accessible
// overflow menu so the header keeps one compact row; the action-error control
// and the trace entry point stay inline at every width.
// Review (point 7): every icon names itself on hover and focus (data-tooltip, styled like the rail's), and the
// theme switch is the rail's alone; the header carries it only where the rail is hidden (compact and phone widths).
export function WorkspaceHeaderActions(props: WorkspaceHeaderActionsProps) {
  const { layoutMode, chatTheme, setChatTheme, statsOpen, stats, codeIntelligence, pullRequests, onOpenTranscript = null } =
    props;
  const themeActionLabel = `Switch to ${chatTheme === "dark" ? "light" : "dark"} theme`;
  const toggleTheme = () =>
    setChatTheme((current) => (current === "dark" ? "light" : "dark"));
  const errorAction = renderErrorAction(props);
  const traceAction = (labelled: boolean) => renderTraceAction(props, labelled);
  const exportItems = buildExportItems(props);
  const handOverItems = buildHandOverItems(props);

  if (layoutMode === "phone") {
    const overflowItems = buildPhoneOverflowItems(props, [...handOverItems, ...exportItems], themeActionLabel, toggleTheme);

    return (
      <div className="workspace__actions workspace__actions--compact">
        {errorAction}
        {traceAction(false)}
        <WorkspaceHeaderOverflowMenu items={overflowItems}>
          {statsOpen ? (
            <StatsPopover stats={stats} codeIntelligence={codeIntelligence} pullRequests={pullRequests} />
          ) : null}
        </WorkspaceHeaderOverflowMenu>
      </div>
    );
  }

  // Desktop: labelled actions instead of a row of bare icons; the two exports share one menu.
  return (
    <div className="workspace__actions">
      {errorAction}
      {renderFilesButton(props)}
      <WorkspaceHeaderOverflowMenu
        items={exportItems}
        trigger={{ label: "Export", ariaLabel: "Export this chat", icon: <ExportIcon /> }}
      />
      {handOverItems.length ? (
        <WorkspaceHeaderOverflowMenu
          items={handOverItems}
          trigger={{ label: "Hand over", ariaLabel: "Hand this chat over", icon: <ExportIcon /> }}
        />
      ) : null}
      {renderStatsShell(props)}
      {layoutMode === "compact" ? (
        <button
          type="button"
          className="icon-action-button"
          aria-label={themeActionLabel}
          data-tooltip={themeActionLabel}
          onClick={toggleTheme}
        >
          <ThemeIcon theme={chatTheme} />
        </button>
      ) : null}
      <span className="workspace__actions-divider" aria-hidden="true" />
      {renderTranscriptButton(onOpenTranscript)}
      {traceAction(true)}
    </div>
  );
}
