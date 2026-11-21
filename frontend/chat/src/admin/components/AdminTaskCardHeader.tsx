// The clickable header row of an Action card: status, badges, last run and the row actions.
import { startedByLine } from "./automation/actionStartedBy";
import type { Dispatch, SetStateAction } from "react";
import { getAgentModeLabel } from "../utils/formatters";
import { bindingBadge } from "./automation/actionDispatchBinding";
import type { PanelTaskRow } from "./taskTypes";
import { formatDate } from "../utils/dateTime";
import { ActionMenu } from "./workflowSurfaces/ActionMenu";

type AdminTaskCardHeaderProps = {
  task: PanelTaskRow;
  isExpanded: boolean;
  inPanel: boolean;
  triggeringTask: string | null;
  onExpandTask: (taskId: string) => void;
  onTriggerTask: (taskId: string) => Promise<void>;
  onOpenTaskForm: (task?: PanelTaskRow) => void;
  setShowTaskForm: Dispatch<SetStateAction<boolean>>;
  onToggleTask: (taskId: string, current: boolean) => Promise<void>;
  onDeleteTask: (taskId: string, name: string) => Promise<void>;
  agentModeNameByKey: Map<string, string>;
  statusColor: Record<string, string>;
};

export function AdminTaskCardHeader({
  task, isExpanded, inPanel, triggeringTask, onExpandTask, onTriggerTask, onOpenTaskForm, setShowTaskForm, onToggleTask,
  onDeleteTask, agentModeNameByKey, statusColor,
}: AdminTaskCardHeaderProps) {
  return (
    <div className="task-item__row" onClick={inPanel ? undefined : () => onExpandTask(task.id)}>
      <div
        className="task-item__status-dot"
        style={{
          background: task.is_active
            ? task.running_count > 0
              ? "#fbbf24"
              : "#86efac"
            : "#4b5563",
        }}
      />
      <div className="task-item__main">
        <div className="task-item__name">{task.name}</div>
        {task.description ? (
          <div className="task-item__desc">{task.description}</div>
        ) : null}
        {/* What starts this action, in words. */}
        <div className="task-item__desc" data-testid="action-started-by">
          {startedByLine(task)}
        </div>
      </div>
      <TaskBadges task={task} agentModeNameByKey={agentModeNameByKey} />
      <TaskLastRun task={task} statusColor={statusColor} />
      <TaskRowActions task={task} inPanel={inPanel} triggeringTask={triggeringTask} onTriggerTask={onTriggerTask}
        onOpenTaskForm={onOpenTaskForm} setShowTaskForm={setShowTaskForm} onToggleTask={onToggleTask} onDeleteTask={onDeleteTask} />
      {inPanel ? null : (
        <svg
          className={`provider-card__chevron ${isExpanded ? "provider-card__chevron--open" : ""}`}
          viewBox="0 0 20 20"
          aria-hidden="true"
        >
          <path d="M5 8l5 5 5-5" />
        </svg>
      )}
    </div>
  );
}

function TaskBadges({ task, agentModeNameByKey }: Pick<AdminTaskCardHeaderProps, "task" | "agentModeNameByKey">) {
  // The Action's current execution setting (not a claim about its past runs).
  const binding = bindingBadge(task);
  return (
  <div className="task-item__meta">
    {!task.is_active ? (
      <span className="task-item__badge admin-task__paused-badge">
        Paused
      </span>
    ) : null}
    <span className="task-item__badge">{task.task_type}</span>
    {binding ? (
      <span
        className="task-item__badge task-item__badge--secondary"
        data-testid="action-binding-badge"
        title={binding.title}
      >
        {binding.label}
      </span>
    ) : null}
    <span className="task-item__badge task-item__badge--secondary">
      {agentModeNameByKey.get(task.agent_type) ||
        getAgentModeLabel(task.agent_type)}
    </span>
    {task.step_count != null && task.step_count > 0 ? (
      <span className="task-item__badge task-item__badge--secondary">
        {task.step_count} step{task.step_count !== 1 ? "s" : ""}
      </span>
    ) : null}
    {task.dependency_count ? (
      <span className="task-item__badge task-item__badge--secondary">
        {task.dependency_count} deps
      </span>
    ) : null}
    {task.dependent_count ? (
      <span className="task-item__badge task-item__badge--secondary">
        {task.dependent_count} dependents
      </span>
    ) : null}
    {task.queued_count ? (
      <span className="task-item__badge task-item__badge--secondary">
        {task.queued_count} queued
        {task.next_queue_priority != null
          ? ` · p${task.next_queue_priority}`
          : ""}
      </span>
    ) : null}
  </div>
  );
}

function TaskLastRun({ task, statusColor }: Pick<AdminTaskCardHeaderProps, "task" | "statusColor">) {
  return (
  <div className="task-item__last-run">
    {task.last_run_status ? (
      <>
        <span
          style={{
            color: statusColor[task.last_run_status] || "var(--muted)",
          }}
        >
          ●
        </span>{" "}
        {task.last_run_status}
        {task.last_run_at ? (
          <span
            className="admin-panel__cell--muted"
            style={{ marginLeft: "0.3rem" }}
          >
            {formatDate(task.last_run_at)}
          </span>
        ) : null}
      </>
    ) : (
      <span className="admin-panel__cell--muted">Never executed</span>
    )}
  </div>
  );
}

type RowActionsProps = Pick<AdminTaskCardHeaderProps, "task" | "inPanel" | "triggeringTask" | "onTriggerTask" | "onOpenTaskForm"
  | "setShowTaskForm" | "onToggleTask" | "onDeleteTask">;

function TaskRowActions({
  task, inPanel, triggeringTask, onTriggerTask, onOpenTaskForm, setShowTaskForm, onToggleTask, onDeleteTask,
}: RowActionsProps) {
  const executeLabel = task.is_active ? "Execute now" : "Paused – resume to run";
  return (
  <div
    className="task-item__actions"
    onClick={(event) => event.stopPropagation()}
  >
    <button
      type="button"
      className="admin-panel__action-btn admin-panel__action-btn--primary"
      disabled={triggeringTask === task.id || !task.is_active}
      onClick={() => void onTriggerTask(task.id)}
      title={executeLabel}
      aria-label={executeLabel}
    >
      {triggeringTask === task.id ? "…" : "▶ Execute"}
    </button>
    <button
      type="button"
      className="admin-panel__icon-btn"
      title="Edit"
      onClick={() => {
        onOpenTaskForm(task);
        setShowTaskForm(true);
      }}
    >
      ✏
    </button>
    <button
      type="button"
      className={`admin-panel__toggle ${
        task.is_active
          ? "admin-panel__toggle--on"
          : "admin-panel__toggle--off"
      }`}
      title={task.is_active ? "Deactivate" : "Activate"}
      onClick={() => void onToggleTask(task.id, task.is_active)}
    >
      <span />
    </button>
    {inPanel ? (
      <ActionMenu
        row={{ objectName: task.name }}
        items={[{ label: "Delete…", danger: true, onSelect: () => void onDeleteTask(task.id, task.name) }]}
      />
    ) : (
      <button
        type="button"
        className="admin-panel__danger-btn"
        onClick={() => void onDeleteTask(task.id, task.name)}
      >
        Delete
      </button>
    )}
  </div>
  );
}
