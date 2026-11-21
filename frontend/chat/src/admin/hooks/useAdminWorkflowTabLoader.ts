import type { Dispatch, SetStateAction } from "react";
import type { PanelTaskRow } from "../components/taskTypes";
import type { PanelScheduler } from "../types/projectQualityTypes.design";
import type { PanelAgent } from "../types/adminPanelTypes.agents";

type ReadJsonFn = <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;

type LoadSchedulersTabDataArgs = {
  readJson: ReadJsonFn;
  tasks: PanelTaskRow[];
  setSchedulers: Dispatch<SetStateAction<PanelScheduler[]>>;
  setTasks: Dispatch<SetStateAction<PanelTaskRow[]>>;
};

export async function loadSchedulersTabData({
  readJson,
  tasks,
  setSchedulers,
  setTasks,
}: LoadSchedulersTabDataArgs) {
  const [schedData, taskData] = await Promise.all([
    readJson<PanelScheduler[]>("/admin/chat/api/panel/schedulers"),
    tasks.length === 0
      ? readJson<PanelTaskRow[]>("/admin/chat/api/panel/tasks")
      : Promise.resolve(null),
  ]);
  setSchedulers(schedData);
  if (taskData) setTasks(taskData);
}

type LoadTasksTabDataArgs = {
  readJson: ReadJsonFn;
  setTasks: Dispatch<SetStateAction<PanelTaskRow[]>>;
  setPanelAgents: Dispatch<SetStateAction<PanelAgent[]>>;
};

export async function loadTasksTabData({
  readJson,
  setTasks,
  setPanelAgents,
}: LoadTasksTabDataArgs) {
  const [taskData, agentData] = await Promise.all([
    readJson<PanelTaskRow[]>("/admin/chat/api/panel/tasks"),
    readJson<PanelAgent[]>("/admin/chat/api/panel/agents"),
  ]);
  setTasks(taskData);
  setPanelAgents(agentData);
}
