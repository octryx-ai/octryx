import type { FormEvent } from "react";
import {
  scheduleSubmitGate,
  type SchedulePreviewState,
} from "../components/scheduler/scheduleModel";
import type { PanelScheduler } from "../components/taskTypes";
import type { UseAdminTaskWorkflowArgs } from "./useAdminTaskWorkflow.types";

type Args = UseAdminTaskWorkflowArgs;

// Saves the scheduler fields: an update keeps the row's switch, a new scheduler starts active.
async function persistScheduler(
  readJson: Args["readJson"],
  setSchedulers: Args["setSchedulers"],
  editingScheduler: PanelScheduler | null,
  fields: Record<string, string>,
) {
  const body = editingScheduler ? fields : { ...fields, is_active: true };
  if (editingScheduler) {
    const updated = await readJson<PanelScheduler>(
      `/admin/chat/api/panel/schedulers/${editingScheduler.id}`,
      { method: "PUT", body: JSON.stringify(body) },
    );
    setSchedulers((prev) =>
      prev.map((scheduler) =>
        scheduler.id === updated.id ? updated : scheduler,
      ),
    );
  } else {
    const created = await readJson<PanelScheduler>(
      "/admin/chat/api/panel/schedulers",
      { method: "POST", body: JSON.stringify(body) },
    );
    setSchedulers((prev) => [created, ...prev]);
  }
}

type SaveSchedulerInput = Pick<
  Args,
  | "readJson"
  | "editingScheduler"
  | "schedulerFormName"
  | "schedulerFormDesc"
  | "schedulerFormCron"
  | "schedulerFormTaskId"
  | "setSchedulerFormError"
  | "setSchedulerFormLoading"
  | "setSchedulers"
> & { closeSchedulerForm: () => void };

// A new or changed schedule is saved only when the latest preview of exactly that expression
// is valid. An unchanged expression is omitted, so a stored value is never rewritten, and
// an update never sends is_active: the toggle is the only way to pause or resume.
async function saveScheduler(
  {
    readJson,
    editingScheduler,
    schedulerFormName,
    schedulerFormDesc,
    schedulerFormCron,
    schedulerFormTaskId,
    setSchedulerFormError,
    setSchedulerFormLoading,
    setSchedulers,
    closeSchedulerForm,
  }: SaveSchedulerInput,
  event: FormEvent,
  preview?: SchedulePreviewState,
) {
  event.preventDefault();
  const gate = scheduleSubmitGate(
    editingScheduler ? editingScheduler.cron_expression : null,
    schedulerFormCron,
    preview,
  );
  if (!gate.canSubmit) {
    setSchedulerFormError(gate.blocker);
    return;
  }
  if (!schedulerFormTaskId) {
    setSchedulerFormError("Choose the action this scheduler runs.");
    return;
  }
  setSchedulerFormLoading(true);
  setSchedulerFormError(null);
  try {
    const fields = {
      name: schedulerFormName,
      description: schedulerFormDesc,
      task_id: schedulerFormTaskId,
      ...(gate.sendCron ? { cron_expression: schedulerFormCron } : {}),
    };
    await persistScheduler(readJson, setSchedulers, editingScheduler, fields);
    closeSchedulerForm();
  } catch (err) {
    const message = (err as { message?: unknown } | null)?.message;
    setSchedulerFormError(typeof message === "string" && message ? message : "Failed");
  } finally {
    setSchedulerFormLoading(false);
  }
}

// Confirmed by the caller in the app (AdminSchedulersTab); a failure is thrown to that dialog.
async function deleteScheduler(
  readJson: Args["readJson"],
  setSchedulers: Args["setSchedulers"],
  id: string,
) {
  await readJson(`/admin/chat/api/panel/schedulers/${id}`, {
    method: "DELETE",
  });
  setSchedulers((prev) => prev.filter((scheduler) => scheduler.id !== id));
}

// Pause or resume. The update answers with the bare row; the list's words (schedule, next run, owner) are kept and
// then reloaded.
async function toggleScheduler(
  readJson: Args["readJson"],
  setSchedulers: Args["setSchedulers"],
  loadTab: Args["loadTab"],
  id: string,
  isActive: boolean,
) {
  const updated = await readJson<PanelScheduler>(
    `/admin/chat/api/panel/schedulers/${id}`,
    {
      method: "PUT",
      body: JSON.stringify({ is_active: !isActive }),
    },
  );
  setSchedulers((prev) =>
    prev.map((scheduler) =>
      scheduler.id === updated.id ? { ...scheduler, ...updated } : scheduler,
    ),
  );
  void loadTab("schedulers");
}

export function useAdminTaskSchedulerActions(args: UseAdminTaskWorkflowArgs) {
  const {
    readJson,
    tasks,
    setShowSchedulerForm,
    setEditingScheduler,
    setSchedulerFormName,
    setSchedulerFormDesc,
    setSchedulerFormCron,
    setSchedulerFormTaskId,
    setSchedulerFormError,
    setSchedulers,
    loadTab,
  } = args;
  const handleOpenSchedulerForm = (scheduler?: PanelScheduler) => {
    setEditingScheduler(scheduler || null);
    setSchedulerFormName(scheduler?.name || "");
    setSchedulerFormDesc(scheduler?.description || "");
    setSchedulerFormCron(scheduler?.cron_expression || "");
    setSchedulerFormTaskId(scheduler?.task_id || "");
    setSchedulerFormError(null);
    setShowSchedulerForm(true);
  };

  const closeSchedulerForm = () => {
    setShowSchedulerForm(false);
    setEditingScheduler(null);
  };

  const handleCreateScheduler = () => {
    handleOpenSchedulerForm();
    if (tasks.length === 0) {
      void loadTab("tasks");
    }
  };

  const handleSaveScheduler = async (
    event: FormEvent,
    preview?: SchedulePreviewState,
  ) => saveScheduler({ ...args, closeSchedulerForm }, event, preview);

  const handleDeleteScheduler = async (id: string, _name: string) =>
    deleteScheduler(readJson, setSchedulers, id);

  const handleToggleScheduler = async (id: string, isActive: boolean) =>
    toggleScheduler(readJson, setSchedulers, loadTab, id, isActive);

  return {
    closeSchedulerForm,
    handleCreateScheduler,
    handleDeleteScheduler,
    handleOpenSchedulerForm,
    handleSaveScheduler,
    handleToggleScheduler,
  };
}
