import { CanvasPanel } from "./CanvasPanel";
import { WorkspaceHeader } from "./WorkspaceHeader";
import { renderWorkspacePrimaryContent } from "./workspacePrimaryContentRender";

type WorkspacePrimarySectionProps = any;

export function WorkspacePrimarySection(props: WorkspacePrimarySectionProps) {
  const {
    workspacePanelOpen,
    selectedSession,
    selectedSessionProjectLabel,
    selectedSessionRuntimePillLabel,
    runtimePillLabel,
    threadStatusLabel,
    statusLabel,
    modeLabel,
    selectedThinkingLevel,
    chatState,
    agentName,
    sending,
    selectedSessionIsRunning,
    taskErrorSummary,
    taskErrorOpen,
    setTaskErrorOpen,
    handleContinue,
    chatTheme,
    setChatTheme,
    statsOpen,
    setStatsOpen,
    selectedThreadCodeIntelligence,
    setTraceOpen,
    setSidebarOpen,
    setWorkspacePanelOpen,
    renameOpen,
    handleRename,
    renameValue,
    setRenameValue,
    showCanvas,
    activeTool,
    setActiveTool,
    activeColor,
    setActiveColor,
    setShowCanvas,
    canvasRef,
    canvasWsRef,
    isDrawingRef,
    lastPosRef,
    drawElement,
    clearCanvas,
    activeWorkflowChipLabel,
  } = props;
  return (
    <section className="workspace__main">
      <WorkspaceHeader
        selectedSession={selectedSession}
        messages={chatState?.selectedMessages ?? []}
        selectedSessionProjectLabel={selectedSessionProjectLabel}
        selectedSessionRuntimePillLabel={selectedSessionRuntimePillLabel}
        runtimePillLabel={runtimePillLabel}
        activeWorkflowChipLabel={activeWorkflowChipLabel}
        threadStatusLabel={threadStatusLabel}
        statusLabel={statusLabel}
        modeLabel={modeLabel}
        thinkingLabel={
          selectedSession
            ? chatState?.selectedThinkingLevel || "light"
            : selectedThinkingLevel
        }
        agentName={agentName}
        sending={sending}
        selectedSessionIsRunning={selectedSessionIsRunning}
        selectedSessionIsArchived={chatState?.selectedSessionIsArchived}
        taskErrorSummary={taskErrorSummary}
        taskErrorOpen={taskErrorOpen}
        setTaskErrorOpen={setTaskErrorOpen}
        onContinue={() => void handleContinue()}
        chatTheme={chatTheme}
        setChatTheme={setChatTheme}
        statsOpen={statsOpen}
        setStatsOpen={setStatsOpen}
        stats={chatState?.selectedThreadStats ?? null}
        codeIntelligence={selectedThreadCodeIntelligence}
        traceEventCount={chatState?.traceEventCount ?? 0}
        onOpenTrace={() => setTraceOpen(true)}
        onOpenSidebar={() => setSidebarOpen(true)}
        workspaceOpen={workspacePanelOpen}
        onToggleWorkspace={() =>
          setWorkspacePanelOpen((current: boolean) => !current)
        }
      />

      {renameOpen && selectedSession ? (
        <form
          className="rename-bar"
          onSubmit={(event) => void handleRename(event)}
        >
          <input
            value={renameValue}
            maxLength={120}
            onChange={(event) => setRenameValue(event.target.value)}
            placeholder="Rename thread"
          />
          <button type="submit" className="solid-button">
            Save
          </button>
        </form>
      ) : null}

      {showCanvas && (
        <CanvasPanel
          activeTool={activeTool}
          setActiveTool={setActiveTool}
          activeColor={activeColor}
          setActiveColor={setActiveColor}
          setShowCanvas={setShowCanvas}
          canvasRef={canvasRef}
          canvasWsRef={canvasWsRef}
          isDrawingRef={isDrawingRef}
          lastPosRef={lastPosRef}
          drawElement={drawElement}
          clearCanvas={clearCanvas}
        />
      )}

      {renderWorkspacePrimaryContent(props)}
    </section>
  );
}
