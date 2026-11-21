import { DataTable, type DataTableColumn } from "../../layout/DataTable";
import { SidePanel } from "../../layout/SidePanel";
import { StatusLabel, type StatusTone } from "../../layout/StatusLabel";
import { formatDate } from "../utils/dateTime";
import { AdminTaskCard } from "./AdminTaskCard";
import type { AdminTasksTabCtx } from "./AdminTasksTab.types";
import { actionTypeLabel, startedByLine, startedByShort } from "./automation/actionStartedBy";
import type { PanelTaskRow } from "./taskTypes";

type AdminTasksListProps = {
  ctx: AdminTasksTabCtx;
};

/** Paused, Running or Active: the configured switch first, then whether a run is going. */
export function actionState(task: PanelTaskRow): { label: string; tone: StatusTone } {
  if (!task.is_active) return { label: "Paused", tone: "neutral" };
  if (task.running_count > 0) return { label: "Running", tone: "info" };
  return { label: "Active", tone: "neutral" };
}

function runWords(status: string): string {
  const words = status.replace(/_/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Unknown";
}

// The columns. The name keeps a readable width; what starts it is a few words, cut with "…" (the full
// sentence is the tooltip), so "Last run" and "State" stay inside the page at 1280 and 1440.
const ACTION_COLUMNS: DataTableColumn<PanelTaskRow>[] = [
  { key: "name", header: "Name", grow: true, minWidth: "14rem", render: (task) => <span title={task.description || undefined}>{task.name}</span> },
  { key: "started", header: "Started by", nowrap: true, clip: "16rem", render: (task) => <span title={startedByLine(task)}>{startedByShort(task)}</span> },
  { key: "type", header: "Type", nowrap: true, render: (task) => <span title={task.task_type}>{actionTypeLabel(task.task_type)}</span> },
  {
    key: "last",
    header: "Last run",
    nowrap: true,
    render: (task) =>
      task.last_run_status ? (
        <>
          <StatusLabel label={runWords(task.last_run_status)} />
          {task.last_run_at ? <span className="admin-panel__cell--muted"> {formatDate(task.last_run_at)}</span> : null}
        </>
      ) : (
        "Never"
      ),
  },
  {
    key: "state",
    header: "State",
    nowrap: true,
    render: (task) => {
      const state = actionState(task);
      return <StatusLabel label={state.label} tone={state.tone} />;
    },
  },
];

/** The step editor's values and handlers, passed through from the tab context to the Action card. */
function stepFormProps(ctx: AdminTasksTabCtx) {
  return {
    taskSteps: ctx.taskSteps,
    onExpandSteps: ctx.onExpandSteps,
    onOpenStepForm: ctx.onOpenStepForm,
    showStepForm: ctx.showStepForm,
    setShowStepForm: ctx.setShowStepForm,
    editingStep: ctx.editingStep,
    setEditingStep: ctx.setEditingStep,
    stepFormName: ctx.stepFormName,
    setStepFormName: ctx.setStepFormName,
    stepFormType: ctx.stepFormType,
    setStepFormType: ctx.setStepFormType,
    stepFormConnector: ctx.stepFormConnector,
    setStepFormConnector: ctx.setStepFormConnector,
    stepFormConnectorAction: ctx.stepFormConnectorAction,
    setStepFormConnectorAction: ctx.setStepFormConnectorAction,
    stepFormInstructions: ctx.stepFormInstructions,
    setStepFormInstructions: ctx.setStepFormInstructions,
    stepFormAgentId: ctx.stepFormAgentId,
    setStepFormAgentId: ctx.setStepFormAgentId,
    panelAgents: ctx.panelAgents,
    stepFormContextFields: ctx.stepFormContextFields,
    setStepFormContextFields: ctx.setStepFormContextFields,
    stepFormConnectorParams: ctx.stepFormConnectorParams,
    setStepFormConnectorParams: ctx.setStepFormConnectorParams,
    stepFormMaxFix: ctx.stepFormMaxFix,
    setStepFormMaxFix: ctx.setStepFormMaxFix,
    stepFormTimeout: ctx.stepFormTimeout,
    setStepFormTimeout: ctx.setStepFormTimeout,
    stepFormError: ctx.stepFormError,
    stepFormLoading: ctx.stepFormLoading,
    onSaveStep: ctx.onSaveStep,
    onMoveStep: ctx.onMoveStep,
    onDeleteStep: ctx.onDeleteStep,
  };
}

// The open Action's detail (steps, dependencies, runs and its controls) in the side panel.
function OpenActionPanel({ ctx, openTask }: { ctx: AdminTasksTabCtx; openTask: PanelTaskRow }) {
  const { taskRuns } = ctx;
  return (
    <SidePanel
      title={openTask.name}
      subtitle="Action"
      onClose={() => ctx.onExpandTask(openTask.id)}
      testId="action-detail-panel"
    >
      <AdminTaskCard
        inPanel
        task={openTask}
        isExpanded
        runs={taskRuns[openTask.id] || []}
        runsError={ctx.taskRunsErrors?.[openTask.id] ?? null}
        // The edit form is its own side panel: this one closes first.
        onOpenTaskForm={(task) => {
          ctx.onExpandTask(openTask.id);
          ctx.onOpenTaskForm(task);
        }}
        triggeringTask={ctx.triggeringTask}
        onExpandTask={ctx.onExpandTask}
        onTriggerTask={ctx.onTriggerTask}
        setShowTaskForm={ctx.setShowTaskForm}
        onToggleTask={ctx.onToggleTask}
        onDeleteTask={ctx.onDeleteTask}
        agentModeNameByKey={ctx.agentModeNameByKey}
        taskDependencies={ctx.taskDependencies}
        onDeleteTaskDependency={ctx.onDeleteTaskDependency}
        taskDependencyTarget={ctx.taskDependencyTarget}
        setTaskDependencyTarget={ctx.setTaskDependencyTarget}
        taskDependencyCondition={ctx.taskDependencyCondition}
        setTaskDependencyCondition={ctx.setTaskDependencyCondition}
        onAddTaskDependency={ctx.onAddTaskDependency}
        {...stepFormProps(ctx)}
        runsLoading={ctx.runsLoading}
        expandedRun={ctx.expandedRun}
        setExpandedRun={ctx.setExpandedRun}
        setTaskRuns={ctx.setTaskRuns}
        loadTaskRuns={ctx.loadTaskRuns}
        cancellingRun={ctx.cancellingRun}
        onCancelRun={ctx.onCancelRun}
      />
    </SidePanel>
  );
}

// The Actions as one compact table; a row opens the existing Action detail (steps,
// dependencies, runs and its controls) in the side panel. Opening and closing use the Action's expand handler, which
// loads its steps, dependencies and runs.
export function AdminTasksList({ ctx }: AdminTasksListProps) {
  const { tasks, expandedTask } = ctx;
  const openTask = tasks.find((task) => task.id === expandedTask) ?? null;

  return (
    <>
      <DataTable<PanelTaskRow>
        label="Actions"
        testId="actions-table"
        rows={tasks}
        rowKey={(task) => task.id}
        onOpen={(task) => {
          if (expandedTask !== task.id) ctx.onExpandTask(task.id);
        }}
        selectedKey={expandedTask}
        empty={{
          text: "No actions yet.",
          action: { label: "New action", onClick: () => ctx.onOpenTaskForm() },
          testId: "actions-empty",
        }}
        columns={ACTION_COLUMNS}
      />
      {openTask ? <OpenActionPanel ctx={ctx} openTask={openTask} /> : null}
    </>
  );
}
