// Project design trace sync tasks: run a sync task, toggle its scheduler, delete a task with its schedulers.
import type { AdminProjectQuality } from "../types/projectQualityTypes";
import type {
  PanelScheduler,
  PanelTaskRow,
  PanelTaskRunRow,
} from "../components/taskTypes";
import { withProjectQualityLoading } from "./projectQualityLoading";
import type { UseAdminProjectDesignTraceArgs } from "./useAdminProjectDesignTrace.types";

type ConfiguredProject = AdminProjectQuality;

// Applies an update to the configured project in the project list and in the open configuration.
function applyToConfiguredProject(
  args: UseAdminProjectDesignTraceArgs,
  projectId: string,
  update: (project: AdminProjectQuality) => AdminProjectQuality,
) {
  const applyToProject = (
    project: AdminProjectQuality,
  ): AdminProjectQuality =>
    project.id === projectId ? update(project) : project;
  args.setAdminProjects((prev) => prev.map(applyToProject));
  args.setConfiguringProjectQuality((prev) =>
    prev ? applyToProject(prev) : prev,
  );
}

async function runSyncTask(
  args: UseAdminProjectDesignTraceArgs,
  configured: ConfiguredProject,
  taskId: string,
) {
  const { readJson } = args;
  await readJson(`/admin/chat/api/panel/tasks/${taskId}/run`, {
    method: "POST",
  });
  const runs = await readJson<PanelTaskRunRow[]>(
    `/admin/chat/api/panel/tasks/${taskId}/runs`,
  );
  applyToConfiguredProject(args, configured.id, (project) => ({
    ...project,
    design_trace_sync_tasks: (project.design_trace_sync_tasks || []).map(
      (task) =>
        task.id === taskId
          ? {
              ...task,
              recent_runs: runs.slice(0, 3),
              run_count: Math.max(task.run_count || 0, runs.length),
              last_run_status: runs[0]?.status || task.last_run_status,
              last_run_at: runs[0]?.started_at || task.last_run_at,
            }
          : task,
    ),
  }));
}

async function toggleSyncScheduler(
  args: UseAdminProjectDesignTraceArgs,
  configured: ConfiguredProject,
  scheduler: PanelScheduler,
) {
  const updated = await args.readJson<PanelScheduler>(
    `/admin/chat/api/panel/schedulers/${scheduler.id}`,
    {
      method: "PUT",
      body: JSON.stringify({ is_active: !scheduler.is_active }),
    },
  );
  applyToConfiguredProject(args, configured.id, (project) => ({
    ...project,
    design_trace_sync_schedulers: (
      project.design_trace_sync_schedulers || []
    ).map((item) => (item.id === updated.id ? updated : item)),
  }));
}

async function deleteSyncTask(
  args: UseAdminProjectDesignTraceArgs,
  configured: ConfiguredProject,
  task: PanelTaskRow,
) {
  const { readJson } = args;
  const linkedSchedulers = (
    configured.design_trace_sync_schedulers || []
  ).filter((item) => item.task_id === task.id);
  for (const scheduler of linkedSchedulers) {
    await readJson(`/admin/chat/api/panel/schedulers/${scheduler.id}`, {
      method: "DELETE",
    });
  }
  await readJson(`/admin/chat/api/panel/tasks/${task.id}`, {
    method: "DELETE",
  });
  applyToConfiguredProject(args, configured.id, (project) => ({
    ...project,
    design_trace_sync_tasks: (project.design_trace_sync_tasks || []).filter(
      (item) => item.id !== task.id,
    ),
    design_trace_sync_schedulers: (
      project.design_trace_sync_schedulers || []
    ).filter((item) => item.task_id !== task.id),
  }));
}

export function createProjectDesignTraceSyncTaskActions(
  args: UseAdminProjectDesignTraceArgs,
) {
  const { configuringProjectQuality } = args;

  const handleRunProjectDesignTraceSyncTask = async (taskId: string) => {
    if (!configuringProjectQuality) return;
    await withProjectQualityLoading(args, "Failed to run trace sync task", () =>
      runSyncTask(args, configuringProjectQuality, taskId),
    );
  };

  const handleToggleProjectDesignTraceSyncScheduler = async (
    scheduler: PanelScheduler,
  ) => {
    if (!configuringProjectQuality) return;
    await withProjectQualityLoading(
      args,
      "Failed to update trace sync scheduler",
      () => toggleSyncScheduler(args, configuringProjectQuality, scheduler),
    );
  };

  const handleDeleteProjectDesignTraceSyncTask = async (task: PanelTaskRow) => {
    if (!configuringProjectQuality) return;
    if (
      !window.confirm(
        `Delete trace sync task "${task.name}" and its scheduler(s)?`,
      )
    )
      return;
    await withProjectQualityLoading(
      args,
      "Failed to delete trace sync task",
      () => deleteSyncTask(args, configuringProjectQuality, task),
    );
  };

  return {
    handleRunProjectDesignTraceSyncTask,
    handleToggleProjectDesignTraceSyncScheduler,
    handleDeleteProjectDesignTraceSyncTask,
  };
}
