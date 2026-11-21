// The detail pages the Mobile app opens above its tabs (a chat, a run, a Work item, a new chat, ...), one per kind.
import type { ReactElement } from "react";
import type { PluginSlotEntry } from "../admin/components/plugins/pluginUiModel";
import type { ProjectOption } from "../chatOptionTypes";
import { ApprovalPage } from "./ApprovalPage";
import { CasePage } from "./CasePage";
import { ChatPage } from "./ChatPage";
import { DevicesPage } from "./DevicesPage";
import { LivePage } from "./LivePage";
import { LocalSessionPage } from "./LocalSessionPage";
import type { PhoneSession } from "./mobileSession";
import type { Case } from "./mobileTasksModel";
import type { LiveSession } from "./mobileLiveSessions";
import type { LocalSession } from "./mobileDeviceChats";
import type { TerminalSession } from "./mobileTerminalSessions";
import { newChatWorkspace } from "./mobileWorkspace";
import { NewChatSheet } from "./NewChatSheet";
import { OperationsPage } from "./OperationsPage";
import type { PhoneApproval } from "./phoneApprovals";
import { PluginPage } from "./PluginPage";
import { RolePage } from "./RolePage";
import { RunPage, type RunLinks } from "./RunPage";
import { SeatPage } from "./SeatPage";
import { TerminalPage } from "./TerminalPage";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";

export type Detail =
  | {
      kind: "chat";
      id: string;
      title: string;
      projectId: string;
      onServer?: boolean;
      localSessionId?: string;
      forkThreadId?: string;
    }
  | { kind: "local"; session: LocalSession }
  | { kind: "live"; session: LiveSession }
  | { kind: "case"; item: Case }
  | { kind: "run"; runId: string; title: string }
  | { kind: "approval"; approval: PhoneApproval }
  | { kind: "devices" }
  | { kind: "operations" }
  | { kind: "role" }
  | { kind: "seat" }
  | { kind: "plugin"; key: string }
  | { kind: "new" }
  | { kind: "terminal"; session: TerminalSession };

type DetailPageProps = {
  detail: Detail | null;
  back: () => void;
  openPage: (page: Detail) => void;
  replacePage: (page: Detail) => void;
  load: () => Promise<void>;
  projects: ProjectOption[];
  workspace: string;
  workspaceNames: Record<string, string>;
  cases: Case[];
  liveSessions: LiveSession[];
  chooseWorkspace: (id: string) => void;
  roleWorkspace: string;
  roleWorkspaceName: string;
  phonePages: PluginSlotEntry[];
  session: PhoneSession | null;
  pluginWorkspace: string;
};
// Each group returns its page, or undefined when the detail is of another kind.
type DetailPage = ReactElement | null | undefined;

function chatPages({ detail, back, openPage, replacePage, projects, workspace }: DetailPageProps): DetailPage {
  if (detail?.kind === "chat")
    return (
      <ChatPage
        key={detail.id}
        sessionId={detail.id}
        title={detail.title}
        projectId={detail.projectId}
        onServer={detail.onServer}
        localSessionId={detail.localSessionId}
        forkThreadId={detail.forkThreadId}
        onOpenRun={(runId, title) => openPage({ kind: "run", runId, title })}
        onBack={back}
      />
    );
  if (detail?.kind === "new")
    return (
      <NewChatSheet
        projects={projects}
        initialProjectId={newChatWorkspace(workspace, projects)}
        onClose={back}
        onStarted={(id, projectId, title, onServer) => replacePage({ kind: "chat", id, title, projectId, onServer })}
      />
    );
  if (detail?.kind === "local") {
    const local = detail.session;
    return (
      <LocalSessionPage
        session={local}
        onBack={back}
        onStarted={(threadId) =>
          replacePage({ kind: "chat", id: threadId, title: local.title, projectId: "", localSessionId: local.id })
        }
      />
    );
  }
  return undefined;
}

function runLinksOf({ openPage, cases }: DetailPageProps): RunLinks {
  return {
    onOpenChat: (id, title, projectId) => openPage({ kind: "chat", id, title, projectId, onServer: true }),
    onOpenWorkItem: (item) =>
      openPage({
        kind: "case",
        item: {
          ...item,
          url: "",
          reporter: "",
          assignee: "",
          priority: "",
          source: "",
          automatic: false,
          run: null,
          ...(cases.find((entry) => entry.id === item.id) ?? {}),
        },
      }),
  };
}

function workPages(props: DetailPageProps): DetailPage {
  const { detail, back, openPage, replacePage, load, workspaceNames } = props;
  if (detail?.kind === "case")
    return (
      <CasePage
        key={detail.item.id}
        item={detail.item}
        workspace={workspaceNames[detail.item.projectId] ?? ""}
        onBack={back}
        onOpenRun={(runId, title) => openPage({ kind: "run", runId, title })}
      />
    );
  if (detail?.kind === "approval")
    return (
      <ApprovalPage
        key={detail.approval.id}
        approval={detail.approval}
        workspace={detail.approval.workspaceId ? workspaceNames[detail.approval.workspaceId] ?? "" : ""}
        onBack={back}
        onSettled={() => void load()}
        onOpenRun={(runId, title) => openPage({ kind: "run", runId, title })}
        onOpenChat={(id, title) =>
          openPage({ kind: "chat", id, title, projectId: detail.approval.workspaceId ?? "", onServer: true })
        }
      />
    );
  if (detail?.kind === "run")
    return <RunPage key={detail.runId} runId={detail.runId} title={detail.title} onBack={back} links={runLinksOf(props)} />;
  if (detail?.kind === "live") {
    const live = detail.session;
    return (
      <LivePage
        session={live}
        onBack={back}
        onForked={(started) => {
          replacePage({
            kind: "chat",
            id: started.thread_id,
            title: started.title || `Fork of ${live.name}`,
            projectId: started.workspace_id,
            localSessionId: started.local_id,
            forkThreadId: started.thread_id,
          });
          void load();
        }}
      />
    );
  }
  return undefined;
}

function workspaceSwitcherOf({ projects, chooseWorkspace }: DetailPageProps, current: string) {
  return projects.length > 1 ? (
    <WorkspaceSwitcher workspace={current} workspaces={projects} onChange={chooseWorkspace} />
  ) : undefined;
}

function accountPages(props: DetailPageProps): ReactElement | null {
  const { detail, back, openPage, workspace, workspaceNames, liveSessions, roleWorkspace, roleWorkspaceName } = props;
  const { phonePages, session, pluginWorkspace } = props;
  if (detail?.kind === "terminal") return <TerminalPage session={detail.session} onBack={back} />;
  if (detail?.kind === "devices")
    return (
      <DevicesPage liveSessions={liveSessions} onBack={back} onOpenLive={(entry) => openPage({ kind: "live", session: entry })} />
    );

  if (detail?.kind === "operations")
    return (
      <OperationsPage
        workspace={workspace}
        onBack={back}
        onOpenRun={(runId, title) => openPage({ kind: "run", runId, title })}
      />
    );

  if (detail?.kind === "seat")
    return (
      <SeatPage
        key={roleWorkspace}
        workspaceId={roleWorkspace}
        workspaceName={roleWorkspaceName}
        switcher={workspaceSwitcherOf(props, roleWorkspace)}
        onBack={back}
      />
    );
  if (detail?.kind === "role")
    return (
      <RolePage
        key={roleWorkspace}
        workspaceId={roleWorkspace}
        workspaceName={roleWorkspaceName}
        switcher={workspaceSwitcherOf(props, roleWorkspace)}
        onBack={back}
      />
    );
  const pluginEntry = detail?.kind === "plugin" ? phonePages.find((page) => page.key === detail.key) : undefined;
  if (detail?.kind === "plugin" && pluginEntry && session)
    return (
      <PluginPage
        entry={pluginEntry}
        workspaceId={pluginWorkspace}
        workspaceName={workspaceNames[pluginWorkspace] ?? ""}
        viewer={{ id: session.user.id, name: session.user.name, role: "member" }}
        switcher={workspaceSwitcherOf(props, pluginWorkspace)}
        onBack={back}
      />
    );
  return null;
}

/** The page for the open detail, or null when no detail is open (the tabs show). */
export function detailPage(props: DetailPageProps): ReactElement | null {
  const chat = chatPages(props);
  if (chat !== undefined) return chat;
  const work = workPages(props);
  if (work !== undefined) return work;
  return accountPages(props);
}
