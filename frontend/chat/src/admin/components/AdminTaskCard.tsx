import { AdminTaskRunsPanel } from "./AdminTaskRunsPanel";
import { AdminTaskStepsSection } from "./AdminTaskStepsSection";
import { stepsSectionProps } from "./adminTaskCardStepsProps";
import "./adminTaskCard.css";
import { AdminTaskCardHeader } from "./AdminTaskCardHeader";
import type { AdminTaskCardProps } from "./adminTaskCardProps";

export function AdminTaskCard(props: AdminTaskCardProps) {
  const {
    task,
    isExpanded,
    runs,
    triggeringTask,
    onExpandTask,
    onTriggerTask,
    onOpenTaskForm,
    setShowTaskForm,
    onToggleTask,
    onDeleteTask,
    agentModeNameByKey,
    runsLoading,
    runsError = null,
    expandedRun,
    setExpandedRun,
    setTaskRuns,
    loadTaskRuns,
    cancellingRun,
    onCancelRun,
    inPanel = false,
  } = props;
  // Theme status ink tokens, readable in both themes (fixed light hexes fail WCAG AA on the light theme's beige).
  const statusColor: Record<string, string> = {
    success: "var(--status-active-ink)",
    failed: "var(--status-error-ink)",
    running: "var(--status-attention-ink)",
    queued: "var(--status-running-ink)",
    cancelled: "var(--status-idle-ink)",
    pending: "var(--status-idle-ink)",
  };

  return (
    <div
      // A paused Action stays fully readable (no global inactive fade); it is marked locally.
      // Admin-task-card scopes the responsive header (adminTaskCard.css) to Action cards only.
      className={`task-item admin-task-card ${isExpanded ? "task-item--expanded" : ""} ${
        !task.is_active ? "admin-task--paused" : ""
      }${inPanel ? " admin-task-card--panel" : ""}`}
    >
      <AdminTaskCardHeader task={task} isExpanded={isExpanded} inPanel={inPanel} triggeringTask={triggeringTask}
        onExpandTask={onExpandTask} onTriggerTask={onTriggerTask} onOpenTaskForm={onOpenTaskForm}
        setShowTaskForm={setShowTaskForm} onToggleTask={onToggleTask} onDeleteTask={onDeleteTask}
        agentModeNameByKey={agentModeNameByKey} statusColor={statusColor} />

      <AdminTaskStepsSection {...stepsSectionProps(props)} />

      <AdminTaskRunsPanel isExpanded={isExpanded} runCount={task.run_count} taskId={task.id} runsLoading={runsLoading}
        runsError={runsError} runs={runs} expandedRun={expandedRun} setExpandedRun={setExpandedRun}
        statusColor={statusColor} taskPaused={!task.is_active} setTaskRuns={setTaskRuns} loadTaskRuns={loadTaskRuns}
        cancellingRun={cancellingRun} handleCancelRun={onCancelRun} />
    </div>
  );
}
