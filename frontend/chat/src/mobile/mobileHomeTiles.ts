// The Home tiles: counts of runs, Work items and Macs, each only when the person can see it.
import type { MyDevice } from "../chat/devices/devicesModel";
import type { HomeTile } from "./HomePage";
import { runCounts, type RunListRow } from "./mobileRuns";
import { inWorkspace } from "./mobileWorkspace";

type HomeTileFacts = {
  runRows: RunListRow[] | null;
  workspace: string;
  openTasks: number | null;
  myTasks: number | null;
  devices: MyDevice[] | null;
  onlineMacs: number;
  onOpenRuns: () => void;
  onOpenWork: (mine: boolean) => void;
  onOpenDevices: () => void;
};

/** Only what the person can see becomes a tile (Work items need the Work operator role; Macs need a device). */
export function homeTiles({
  runRows,
  workspace,
  openTasks,
  myTasks,
  devices,
  onlineMacs,
  onOpenRuns,
  onOpenWork,
  onOpenDevices,
}: HomeTileFacts): HomeTile[] {
  const tiles: HomeTile[] = [];
  if (runRows !== null) {
    const counts = runCounts(runRows.filter((row) => inWorkspace(row.projectId, workspace)));
    tiles.push({
      key: "runs",
      label: "Runs",
      value: counts.active,
      hint: counts.needs ? `${counts.needs} waiting for you` : "going on",
      tone: counts.needs ? "attention" : undefined,
      onOpen: onOpenRuns,
    });
  }
  if (openTasks !== null)
    tiles.push({ key: "work", label: "Work items", value: openTasks, hint: "open", onOpen: () => onOpenWork(false) });
  if (myTasks !== null)
    tiles.push({ key: "mine", label: "Assigned to you", value: myTasks, hint: "open", onOpen: () => onOpenWork(true) });
  if (devices !== null)
    tiles.push({
      key: "macs",
      label: "Macs online",
      value: `${onlineMacs} of ${devices.length}`,
      hint: devices.length ? (onlineMacs ? "ready for jobs" : "all offline") : "none connected yet",
      onOpen: onOpenDevices,
    });
  return tiles;
}
