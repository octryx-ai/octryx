// The phone's tab pages (Home, Chats, Runs, Work, More) with the start-run sheet and the bottom tab bar.
import type { Dispatch, ReactNode, SetStateAction } from "react";
import type { AttentionItem } from "../chat/companion/companionTypes";
import type { MyDevice } from "../chat/devices/devicesModel";
import type { PluginSlotEntry } from "../admin/components/plugins/pluginUiModel";
import { ChatsPage } from "./ChatsPage";
import { HomePage } from "./HomePage";
import { homeTiles } from "./mobileHomeTiles";
import { signOutPhone, type PhoneSession } from "./mobileSession";
import type { Case } from "./mobileTasksModel";
import type { DeviceThread, LocalSession } from "./mobileDeviceChats";
import type { LiveSession } from "./mobileLiveSessions";
import type { TerminalSession } from "./mobileTerminalSessions";
import type { Usage } from "./mobileUsageModel";
import type { Detail } from "./mobileDetailPages";
import { MorePage } from "./MorePage";
import type { RunListRow } from "./mobileRuns";
import type { PhoneApproval } from "./phoneApprovals";
import { RunsPage } from "./RunsPage";
import { StartRunSheet } from "./StartRunSheet";
import { TabBar, type TabItem, type TabKey } from "./TabBar";
import { moreLinks } from "./mobileMoreLinks";
import { TasksPage } from "./TasksPage";

export type MobileTabScreenProps = {
  tab: TabKey;
  setTab: Dispatch<SetStateAction<TabKey>>;
  switcher: ReactNode;
  workspace: string;
  workspaceNames: Record<string, string>;
  needs: AttentionItem[];
  shownApprovals: PhoneApproval[];
  shownThreads: DeviceThread[];
  shownCases: Case[];
  sessions: TerminalSession[];
  liveSessions: LiveSession[];
  localSessions: LocalSession[];
  usage: Usage | null;
  loading: boolean;
  error: string;
  devices: MyDevice[] | null;
  runRows: RunListRow[] | null;
  openTasks: number | null;
  myTasks: number | null;
  session: PhoneSession | null;
  roleWorkspaceName: string;
  phonePages: PluginSlotEntry[];
  workMine: boolean;
  setWorkMine: Dispatch<SetStateAction<boolean>>;
  startingRun: boolean;
  setStartingRun: Dispatch<SetStateAction<boolean>>;
  setPhase: Dispatch<SetStateAction<"loading" | "signedOut" | "ready">>;
  openPage: (page: Detail) => void;
  openItem: (item: AttentionItem) => void;
  openThread: (thread: DeviceThread) => void;
  openLocal: (local: LocalSession) => void;
};

function HomeAndChatsTabs({ props, tiles, newChat }: { props: MobileTabScreenProps; tiles: ReturnType<typeof homeTiles>; newChat: () => void }) {
  const { tab, setTab, switcher, openPage, openThread, loading, sessions, workspaceNames } = props;
  return (
    <>
      {tab === "home" && (
        <HomePage
          switcher={switcher}
          needs={props.needs}
          approvals={props.shownApprovals}
          tiles={tiles}
          threads={props.shownThreads}
          sessions={sessions}
          cases={props.shownCases}
          workspaces={workspaceNames}
          usage={props.usage}
          loading={loading}
          error={props.error}
          onOpenItem={props.openItem}
          onOpenApproval={(approval) => openPage({ kind: "approval", approval })}
          onOpenCase={(item) => openPage({ kind: "case", item })}
          onOpenThread={openThread}
          onOpenSession={(entry) => openPage({ kind: "terminal", session: entry })}
          onAllChats={() => setTab("chats")}
          onNewChat={newChat}
        />
      )}
      {tab === "chats" && (
        <ChatsPage
          switcher={switcher}
          threads={props.shownThreads}
          sessions={sessions}
          liveSessions={props.liveSessions}
          localSessions={props.localSessions}
          loading={loading}
          onOpenThread={openThread}
          onOpenSession={(entry) => openPage({ kind: "terminal", session: entry })}
          onOpenLive={(entry) => openPage({ kind: "live", session: entry })}
          onOpenLocal={props.openLocal}
          onNewChat={newChat}
        />
      )}
    </>
  );
}

function RunsWorkMoreTabs({ props, onlineMacs }: { props: MobileTabScreenProps; onlineMacs: number }) {
  const { tab, switcher, workspace, workspaceNames, openPage, setStartingRun, session, workMine } = props;
  return (
    <>
      {tab === "runs" && (
        <RunsPage
          workspace={workspace}
          switcher={switcher}
          onOpen={(row) => openPage({ kind: "run", runId: row.id, title: row.subject })}
          onStart={() => setStartingRun(true)}
          onOperations={() => openPage({ kind: "operations" })}
        />
      )}
      {props.startingRun && (
        <StartRunSheet
          workspace={workspace}
          workspaces={workspaceNames}
          onClose={() => setStartingRun(false)}
          onStarted={(runId, title) => {
            setStartingRun(false);
            openPage({ kind: "run", runId, title });
          }}
        />
      )}
      {tab === "work" && (
        <TasksPage
          key={workMine ? "mine" : "all"}
          initialMine={workMine}
          workspaces={workspaceNames}
          workspace={workspace}
          switcher={switcher}
          onOpen={(item) => openPage({ kind: "case", item })}
        />
      )}
      {tab === "more" && session && (
        <MorePage
          session={session}
          links={moreLinks(props, onlineMacs)} onSignOut={() => void signOutPhone().finally(() => props.setPhase("signedOut"))} />
      )}
    </>
  );
}

export function MobileTabScreen(props: MobileTabScreenProps) {
  const { tab, setTab, devices, openPage, setWorkMine, needs, shownApprovals } = props;
  const onlineMacs = devices?.filter((device) => device.connected).length ?? 0;
  const openWork = (mine: boolean) => {
    setWorkMine(mine);
    setTab("work");
  };
  const tiles = homeTiles({
    runRows: props.runRows,
    workspace: props.workspace,
    openTasks: props.openTasks,
    myTasks: props.myTasks,
    devices,
    onlineMacs,
    onOpenRuns: () => setTab("runs"),
    onOpenWork: openWork,
    onOpenDevices: () => openPage({ kind: "devices" }),
  });
  const tabs: TabItem[] = [
    { key: "home", label: "Home", icon: "home", badge: needs.length + shownApprovals.length },
    { key: "chats", label: "Chats", icon: "chats" },
    { key: "runs", label: "Runs", icon: "runs" },
    { key: "work", label: "Work", icon: "work" },
    { key: "more", label: "More", icon: "more" },
  ];
  const newChat = () => openPage({ kind: "new" });

  return (
    <div className="m-screen m-tabbed">
      <HomeAndChatsTabs props={props} tiles={tiles} newChat={newChat} />
      <RunsWorkMoreTabs props={props} onlineMacs={onlineMacs} />
      <TabBar
        tabs={tabs}
        active={tab}
        onSelect={(next) => {
          setTab(next);
          window.scrollTo(0, 0);
        }}
      />
    </div>
  );
}
