// State of the phone app: sign-in phase, tab, detail pages, Workspace choice and the lists the tabs show.
import { useMemo, useState } from "react";
import { needsYou } from "../chat/companion/companionGroups";
import { type AttentionItem } from "../chat/companion/companionTypes";
import type { MyDevice } from "../chat/devices/devicesModel";
import type { ProjectOption } from "../chatOptionTypes";
import type { PhoneSession } from "./mobileSession";
import { parseHash, type DeviceThread, type LocalSession } from "./mobileDeviceChats";
import { type Case } from "./mobileTasksModel";
import { type LiveSession } from "./mobileLiveSessions";
import { type TerminalSession } from "./mobileTerminalSessions";
import { type Usage } from "./mobileUsageModel";
import { inWorkspace, readWorkspaceChoice, resolveWorkspace } from "./mobileWorkspace";
import type { Detail } from "./mobileDetailPages";
import type { RunListRow } from "./mobileRuns";
import { withoutApprovals, type PhoneApproval } from "./phoneApprovals";
import type { TabKey } from "./TabBar";
import { useDetailStack } from "./useDetailStack";

export const browserStore = () => {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
};

export type MobilePhase = "loading" | "signedOut" | "ready";

export function useMobileAppState() {
  const [phase, setPhase] = useState<MobilePhase>("loading");
  const [session, setSession] = useState<PhoneSession | null>(null);
  const [tab, setTab] = useState<TabKey>("home");
  const { page: detail, open: openPage, replace: replacePage, back, reset: resetPages } = useDetailStack<Detail>();
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [choice, setChoice] = useState(() => readWorkspaceChoice(browserStore()));
  const workspace = resolveWorkspace(choice, projects);
  // Where a task lives: its Workspace's name (the person's Workspaces, from the bootstrap).
  const workspaceNames = useMemo(
    () => Object.fromEntries(projects.map((project) => [project.id, project.name])),
    [projects],
  );
  const [threads, setThreads] = useState<DeviceThread[]>([]);
  const [sessions, setSessions] = useState<TerminalSession[]>([]);
  const [localSessions, setLocalSessions] = useState<LocalSession[]>([]);
  const [liveSessions, setLiveSessions] = useState<LiveSession[]>([]);
  const [devices, setDevices] = useState<MyDevice[] | null>(null);
  const [cases, setCases] = useState<Case[]>([]);
  const [runRows, setRunRows] = useState<RunListRow[] | null>(null);
  const [openTasks, setOpenTasks] = useState<number | null>(null);
  const [myTasks, setMyTasks] = useState<number | null>(null);
  const [items, setItems] = useState<AttentionItem[] | null>(null);
  // The pending approvals this person may decide, decided on the phone.
  const [approvals, setApprovals] = useState<PhoneApproval[]>([]);
  // A notification opens /m/#item=<key>; the entry opens once the queue is loaded.
  const [pendingItem, setPendingItem] = useState(() => parseHash(window.location.hash).item ?? "");
  const [usage, setUsage] = useState<Usage | null>(null);
  const [startingRun, setStartingRun] = useState(false);
  // The Work tab opens on all open Work items, or on the person's own from the "Assigned to you" tile.
  const [workMine, setWorkMine] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  return {
    phase, setPhase, session, setSession, tab, setTab, detail, openPage, replacePage, back, resetPages, projects,
    setProjects, choice, setChoice, workspace, workspaceNames, threads, setThreads, sessions, setSessions,
    localSessions, setLocalSessions, liveSessions, setLiveSessions, devices, setDevices, cases, setCases, runRows,
    setRunRows, openTasks, setOpenTasks, myTasks, setMyTasks, items, setItems, approvals, setApprovals, pendingItem,
    setPendingItem, usage, setUsage, startingRun, setStartingRun, workMine, setWorkMine, loading, setLoading, error,
    setError,
  };
}

export type MobileAppState = ReturnType<typeof useMobileAppState>;

// What the phone shows follows the Workspace choice; the platform already limits it to the person's scope.
export function useShownLists({ threads, cases, approvals, items, workspace }: MobileAppState) {
  const shownThreads = useMemo(() => threads.filter((thread) => inWorkspace(thread.projectId, workspace)), [threads, workspace]);
  const shownCases = useMemo(() => cases.filter((item) => inWorkspace(item.projectId, workspace)), [cases, workspace]);
  const shownApprovals = useMemo(
    () => approvals.filter((item) => inWorkspace(item.workspaceId, workspace)),
    [approvals, workspace],
  );
  // An approval shows as its own card; its chat entry and its run's gate are not repeated (see withoutApprovals).
  const needs = useMemo(
    () => withoutApprovals(needsYou(items ?? []), approvals).filter((item) => inWorkspace(item.workspace?.id, workspace)),
    [items, approvals, workspace],
  );
  return { shownThreads, shownCases, shownApprovals, needs };
}
