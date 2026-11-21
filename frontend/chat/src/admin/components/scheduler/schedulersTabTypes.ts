// Schedulers tab: the context the admin panel hands in (schedulers, actions, the form state and its handlers).
import type { Dispatch, FormEvent, SetStateAction } from "react";
import type { SchedulePreviewState } from "./scheduleModel";
import type { PanelScheduler } from "../taskTypes";

export type SchedulerRow = PanelScheduler;

export type TaskOptionRow = {
  id: string;
  name: string;
};

export type AdminSchedulersTabCtx = {
  schedulers: SchedulerRow[];
  setSchedulers: Dispatch<SetStateAction<PanelScheduler[]>>;
  tasks: TaskOptionRow[];
  showSchedulerForm: boolean;
  editingScheduler: SchedulerRow | null;
  schedulerFormName: string;
  setSchedulerFormName: Dispatch<SetStateAction<string>>;
  schedulerFormDesc: string;
  setSchedulerFormDesc: Dispatch<SetStateAction<string>>;
  schedulerFormCron: string;
  setSchedulerFormCron: Dispatch<SetStateAction<string>>;
  schedulerFormTaskId: string;
  setSchedulerFormTaskId: Dispatch<SetStateAction<string>>;
  schedulerFormLoading: boolean;
  schedulerFormError: string | null;
  onCreateScheduler: () => void;
  onOpenSchedulerForm: (scheduler: SchedulerRow) => void;
  onCloseSchedulerForm: () => void;
  onSaveScheduler: (
    event: FormEvent,
    preview: SchedulePreviewState,
  ) => void | Promise<void>;
  onToggleScheduler: (id: string, isActive: boolean) => void | Promise<void>;
  onDeleteScheduler: (id: string, name: string) => void | Promise<void>;
  readJson?: <T>(input: string, init?: RequestInit) => Promise<T>;
};
