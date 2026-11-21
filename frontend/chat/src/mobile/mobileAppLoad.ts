// Loads everything the phone's tab pages show (chats, sessions, runs, tasks, Macs, attention, approvals, usage).
import type { Dispatch, SetStateAction } from "react";
import { needsYou } from "../chat/companion/companionGroups";
import { readAttention } from "../chat/companion/companionRead";
import { type AttentionItem } from "../chat/companion/companionTypes";
import { readDevice, type MyDevice } from "../chat/devices/devicesModel";
import type { ProjectOption } from "../chatOptionTypes";
import type { ThreadGroup } from "../chatThreadTypes";
import { loadAttentionQueue, loadBootstrap, loadCaseRuns, loadDecidableApprovals, loadDevices, loadLive, loadLocalSessions, loadOpenSessions, loadTasks, loadUsage } from "./mobileApi";
import { type MobileError } from "./mobileSession";
import { chatThreads, readLocalSessions, type DeviceThread, type LocalSession } from "./mobileDeviceChats";
import { readCases, readTaskCounts, type Case } from "./mobileTasksModel";
import { readLiveSessions, type LiveSession } from "./mobileLiveSessions";
import { readOpenSessions, type TerminalSession } from "./mobileTerminalSessions";
import { readUsage, type Usage } from "./mobileUsageModel";
import { resolveWorkspace, usageWorkspace } from "./mobileWorkspace";
import { readRunRows, type RunListRow } from "./mobileRuns";
import { readDecidable, withoutApprovals, type PhoneApproval } from "./phoneApprovals";

type Setter<T> = Dispatch<SetStateAction<T>>;

export type MobileAppDataSetters = {
  setLoading: Setter<boolean>;
  setThreads: Setter<DeviceThread[]>;
  setProjects: Setter<ProjectOption[]>;
  setSessions: Setter<TerminalSession[]>;
  setLocalSessions: Setter<LocalSession[]>;
  setLiveSessions: Setter<LiveSession[]>;
  setCases: Setter<Case[]>;
  setRunRows: Setter<RunListRow[] | null>;
  setOpenTasks: Setter<number | null>;
  setMyTasks: Setter<number | null>;
  setDevices: Setter<MyDevice[] | null>;
  setItems: Setter<AttentionItem[] | null>;
  setApprovals: Setter<PhoneApproval[]>;
  setUsage: Setter<Usage | null>;
  setError: Setter<string>;
};

export async function loadMobileAppData(
  choice: string,
  {
    setLoading,
    setThreads,
    setProjects,
    setSessions,
    setLocalSessions,
    setLiveSessions,
    setCases,
    setRunRows,
    setOpenTasks,
    setMyTasks,
    setDevices,
    setItems,
    setApprovals,
    setUsage,
    setError,
  }: MobileAppDataSetters,
) {
  setLoading(true);
  try {
    const [state, attention, decidable] = await Promise.all([
      loadBootstrap(),
      loadAttentionQueue().catch(() => null),
      loadDecidableApprovals().catch(() => null),
    ]);
    const list = chatThreads(state.activeThreadGroups as ThreadGroup[] | undefined);
    const options = (state.projects as ProjectOption[] | undefined) ?? [];
    const scope = resolveWorkspace(choice, options);
    setThreads(list);
    setProjects(options);
    const [open, local, live, mine, all, runs, macs] = await Promise.all([
      loadOpenSessions().catch(() => null),
      loadLocalSessions().catch(() => null),
      loadLive().catch(() => null),
      // Tasks: the open Work items assigned to the person, and how many are open in all.
      // Only people with the Work operator role see Work items; everyone else gets none.
      loadTasks({ mine: true, limit: 20, project: scope }).catch(() => null),
      loadTasks({ limit: 1, project: scope }).catch(() => null),
      loadCaseRuns(scope).catch(() => null),
      loadDevices().catch(() => null),
    ]);
    setSessions(readOpenSessions(open));
    setLocalSessions(readLocalSessions(local));
    setLiveSessions(readLiveSessions(live));
    setCases(readCases(mine, runs));
    setRunRows(runs ? readRunRows(runs) : null);
    setOpenTasks(all ? readTaskCounts(all).total : null);
    setMyTasks(mine ? readTaskCounts(mine).total : null);
    const rawDevices = (macs as { items?: unknown[] } | null)?.items;
    setDevices(
      Array.isArray(rawDevices) ? rawDevices.map(readDevice).filter((item): item is MyDevice => item !== null) : null,
    );
    const queue = readAttention(attention)?.items ?? [];
    const pending = readDecidable(decidable);
    setItems(queue);
    setApprovals(pending);
    const badge = navigator as Navigator & {
      setAppBadge?: (count: number) => Promise<void>;
      clearAppBadge?: () => Promise<void>;
    };
    // The badge counts each thing to decide once: an approval and its attention entry are one.
    const waiting = withoutApprovals(needsYou(queue), pending).length + pending.length;
    void (waiting ? badge.setAppBadge?.(waiting) : badge.clearAppBadge?.())?.catch(() => undefined);
    const budget = usageWorkspace(scope, options, list[0]?.projectId);
    if (budget)
      loadUsage(budget).then(
        (raw) => setUsage(readUsage(raw)),
        () => setUsage(null),
      );
    setError("");
  } catch (reason) {
    if ((reason as MobileError).status !== 401) setError("The platform could not be reached. Is the VPN on?");
  } finally {
    setLoading(false);
  }
}
