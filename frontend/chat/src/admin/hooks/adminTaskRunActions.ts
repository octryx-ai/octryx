// Action requests: runs, dependencies, trigger, cancel, toggle and delete.
import { beginRunStatusRequest, mergeTaskSummary } from "./actionRunStatusSync";
import type {
  PanelTaskRow,
  PanelTaskDependencyStateRow,
  PanelTaskRunRow,
} from "../components/taskTypes";
import type { UseAdminTaskWorkflowArgs } from "./useAdminTaskWorkflow.types";

type Args = UseAdminTaskWorkflowArgs;
const TASKS_URL = "/admin/chat/api/panel/tasks";
const failureText = (err: unknown) => (err instanceof Error ? err.message : "Failed");

function clearRunsError(args: Args, taskId: string) {
  args.setTaskRunsErrors?.((prev) => {
    if (!(taskId in prev)) return prev;
    const next = { ...prev };
    delete next[taskId];
    return next;
  });
}

// Expanding an Action uses its cached runs; `refresh` (Execute, Cancel, the Refresh
// button) always asks again, for the run list and the Action's summary together. Only the
// newest request for an Action may write. A failed refresh keeps the last known rows and says so.
// There is no timer and no polling.
export async function loadRuns(args: Args, taskId: string, refresh: boolean) {
  const { readJson, setRunsLoading } = args;
  if (!refresh && args.taskRuns[taskId]) return;
  const isCurrent = beginRunStatusRequest(taskId);
  setRunsLoading(taskId);
  try {
    const [runs, summaries] = await Promise.all([
      readJson<PanelTaskRunRow[]>(`${TASKS_URL}/${taskId}/runs`),
      refresh ? readJson<PanelTaskRow[]>(TASKS_URL) : Promise.resolve(null),
    ]);
    if (!isCurrent()) return;
    args.setTaskRuns((prev) => ({ ...prev, [taskId]: runs }));
    if (summaries) {
      args.setTasks((prev) => mergeTaskSummary(prev, summaries, taskId));
    }
    clearRunsError(args, taskId);
  } catch (err) {
    if (!isCurrent()) return;
    const message = (err as { message?: unknown } | null)?.message;
    args.setTaskRunsErrors?.((prev) => ({
      ...prev,
      [taskId]: typeof message === "string" && message ? message : "Request failed",
    }));
  } finally {
    if (isCurrent()) setRunsLoading(null);
  }
}

export async function loadDependencies(args: Args, taskId: string) {
  const data = await args.readJson<PanelTaskDependencyStateRow>(`${TASKS_URL}/${taskId}/dependencies`);
  args.setTaskDependencies((prev) => ({ ...prev, [taskId]: data }));
  args.setTaskDependencyTarget((prev) => ({
    ...prev,
    [taskId]: prev[taskId] || data.available_tasks[0]?.id || "",
  }));
  args.setTaskDependencyCondition((prev) => ({ ...prev, [taskId]: prev[taskId] || "success" }));
}

export async function addDependency(args: Args, taskId: string) {
  const dependsOnTaskId = args.taskDependencyTarget[taskId];
  if (!dependsOnTaskId) return;
  try {
    const updated = await args.readJson<PanelTaskDependencyStateRow>(`${TASKS_URL}/${taskId}/dependencies`, {
      method: "POST",
      body: JSON.stringify({
        depends_on_task_id: dependsOnTaskId,
        condition: args.taskDependencyCondition[taskId] || "success",
      }),
    });
    args.setTaskDependencies((prev) => ({ ...prev, [taskId]: updated }));
    const tasksUpdated = await args.readJson<PanelTaskRow[]>(TASKS_URL);
    args.setTasks(tasksUpdated);
  } catch (err) {
    alert(failureText(err));
  }
}

export async function deleteDependency(args: Args, taskId: string, dependencyId: string) {
  try {
    await args.readJson(`${TASKS_URL}/${taskId}/dependencies/${dependencyId}`, { method: "DELETE" });
    await loadDependencies(args, taskId);
    const tasksUpdated = await args.readJson<PanelTaskRow[]>(TASKS_URL);
    args.setTasks(tasksUpdated);
  } catch (err) {
    alert(failureText(err));
  }
}

export async function triggerTask(args: Args, taskId: string) {
  args.setTriggeringTask(taskId);
  try {
    await args.readJson(`${TASKS_URL}/${taskId}/run`, { method: "POST" });
  } catch (err) {
    alert(failureText(err));
    return;
  } finally {
    args.setTriggeringTask(null);
  }
  // One refresh of what the server now reports (the new run is usually still queued).
  await loadRuns(args, taskId, true);
}

export async function cancelRun(args: Args, taskId: string, runId: string) {
  args.setCancellingRun(runId);
  try {
    await args.readJson(`${TASKS_URL}/${taskId}/runs/${runId}/cancel`, { method: "POST" });
    args.setTaskRuns((prev) => ({
      ...prev,
      [taskId]: (prev[taskId] || []).map((run) => (run.id === runId ? { ...run, status: "cancelled" } : run)),
    }));
  } catch (err) {
    alert(failureText(err));
    return;
  } finally {
    args.setCancellingRun(null);
  }
  await loadRuns(args, taskId, true);
}

export async function toggleTask(args: Args, taskId: string, current: boolean) {
  try {
    const updated = await args.readJson<PanelTaskRow>(`${TASKS_URL}/${taskId}`, {
      method: "PUT",
      body: JSON.stringify({ is_active: !current }),
    });
    args.setTasks((prev) => prev.map((task) => (task.id === taskId ? updated : task)));
  } catch (err) {
    alert(failureText(err));
  }
}

export async function deleteTask(args: Args, taskId: string, name: string) {
  if (!confirm(`Delete task "${name}"?`)) return;
  try {
    await args.readJson(`${TASKS_URL}/${taskId}`, { method: "DELETE" });
    args.setTasks((prev) => prev.filter((task) => task.id !== taskId));
    if (args.expandedTask === taskId) args.setExpandedTask(null);
  } catch (err) {
    alert(failureText(err));
  }
}
