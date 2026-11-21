import { AdminTaskForm } from "./AdminTaskForm";
import { AdminTasksList } from "./AdminTasksList";
import { AdminTasksTabHeader } from "./AdminTasksTabHeader";
import type {
  AdminTasksTabCtx,
  AdminTasksTabProps,
} from "./AdminTasksTab.types";

export function AdminTasksTab({ ctx }: AdminTasksTabProps) {
  const typedCtx = ctx as AdminTasksTabCtx;

  return (
    <div>
      <AdminTasksTabHeader ctx={typedCtx} />
      <AdminTaskForm
        showTaskForm={typedCtx.showTaskForm}
        editingTask={typedCtx.editingTask}
        taskFormName={typedCtx.taskFormName}
        setTaskFormName={typedCtx.setTaskFormName}
        taskFormDesc={typedCtx.taskFormDesc}
        setTaskFormDesc={typedCtx.setTaskFormDesc}
        taskFormAgentDefId={typedCtx.taskFormAgentDefId}
        setTaskFormAgentDefId={typedCtx.setTaskFormAgentDefId}
        taskFormProjectId={typedCtx.taskFormProjectId}
        setTaskFormProjectId={typedCtx.setTaskFormProjectId}
        projects={typedCtx.projects ?? []}
        panelAgents={typedCtx.panelAgents}
        taskFormMaxIterations={typedCtx.taskFormMaxIterations}
        setTaskFormMaxIterations={typedCtx.setTaskFormMaxIterations}
        taskFormConfig={typedCtx.taskFormConfig}
        setTaskFormConfig={typedCtx.setTaskFormConfig}
        taskFormError={typedCtx.taskFormError}
        taskFormLoading={typedCtx.taskFormLoading}
        onSaveTask={typedCtx.onSaveTask}
        onCloseTaskForm={typedCtx.onCloseTaskForm}
      />
      <AdminTasksList ctx={typedCtx} />
    </div>
  );
}
