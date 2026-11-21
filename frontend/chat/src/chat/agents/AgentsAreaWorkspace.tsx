import { useCallback, useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { AreaTitle } from "../workspace/AreaTitle";

import type { ProjectOption } from "../../chatOptionTypes";
import { WorkspaceDataClassificationCard } from "../../admin/components/dataClassification/WorkspaceDataClassificationCard";
import { useActiveWorkspace } from "../useActiveWorkspace";
import { ChooseWorkspaceLine } from "../workspace/ChooseWorkspaceLine";
import { loadAgentPresence, removeAgentPresence } from "./agentPresenceApi";
import { PRESENCE_POLL_MS, presenceErrorText, readPresence } from "./agentPresenceModel";
import type { ConnectedClient } from "./agentPresenceModel";
import { AGENTS_FOCUS_EVENT, readUrlAgentsFocus, readUrlAgentsView, takeAgentsFocus } from "./agentsFocus";
import type { AgentsFocus } from "./agentsFocus";
import { AGENTS_NAV_ITEMS } from "./AgentsAreaNav";
import { readAgentsSidebarCollapsed, storeAgentsSidebarCollapsed } from "./agentsSidebarPreference";
import type { AgentsNavKey } from "./AgentsAreaNav";
import type { AdminTab } from "../../admin/types/adminPanelTypes.governance";
import { AgentsClaims } from "./AgentsClaims";
import { AgentsConnectedClients } from "./AgentsConnectedClients";
import { AgentsHandoffs } from "./AgentsHandoffs";
import { AgentsHandoffPolicy } from "./AgentsHandoffPolicy";
import { AgentsInstallClient } from "./AgentsInstallClient";
import { AgentsMessageBoard } from "./AgentsMessageBoard";
import { AgentsSeatRefusal } from "./AgentsSeatRefusal";
import { AgentsWorkspacePolicy } from "./AgentsWorkspacePolicy";
import { WorkspaceContentHandling } from "../../admin/components/contentSecurity/WorkspaceContentHandling";
import { DeviceRunsPolicyCard } from "../devices/DeviceRunsPolicyCard";
import "./agents.css";
import { PageHeader } from "../../layout/PageHeader";
import { LoadingState } from "../../layout/LoadingState";
import { EmptyLine } from "../../layout/EmptyLine";
import { AgentsAreaMenuNav } from "./AgentsAreaMenuNav";
import { agentsAreaGroup } from "./agentsAreaMenu";

type Focus = { nonce: number; messageId: string | null; takeoverId: string | null; workItemId: string | null;
  handoffClaimId: string | null };

// A focus from the bell (the bell already selected the Workspace) or from an in-app notification link on load:
// open the view on the item. Returns the cleanup of the focus listener.
function followAgentsFocus(setView: (view: AgentsNavKey) => void, setFocus: Dispatch<SetStateAction<Focus>>) {
  const apply = (next: AgentsFocus | null) => {
    if (!next) return;
    setView(next.view);
    setFocus((previous) => ({ nonce: previous.nonce + 1, messageId: next.messageId, takeoverId: next.takeoverId ?? null,
      workItemId: next.workItemId ?? null, handoffClaimId: next.handoffClaimId ?? null }));
  };
  apply(takeAgentsFocus() ?? readUrlAgentsFocus(window.location.search));
  const onFocus = () => apply(takeAgentsFocus());
  window.addEventListener(AGENTS_FOCUS_EVENT, onFocus);
  return () => window.removeEventListener(AGENTS_FOCUS_EVENT, onFocus);
}

// The connected clients of the Workspace while the clients view is shown: polled every `pollMs` while the page is
// visible, and refreshed at once when it becomes visible again.
function usePresenceClients(workspaceId: string | null, view: AgentsNavKey, pollMs: number) {
  const [clients, setClients] = useState<ConnectedClient[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async (projectId: string, isCurrent: () => boolean) => {
    try {
      const listed = readPresence(await loadAgentPresence(projectId));
      if (!isCurrent()) return;
      if (listed === null) {
        setProblem("The server's answer was not a list of agent clients.");
        setClients(null);
      } else {
        setProblem(null);
        setClients(listed);
      }
    } catch (error) {
      if (!isCurrent()) return;
      setProblem(presenceErrorText(error).text);
      setClients(null);
    }
  }, []);

  useEffect(() => {
    if (!workspaceId || view !== "clients") return undefined;
    let current = true;
    setClients(null);
    setProblem(null);
    void load(workspaceId, () => current);
    const visible = () => document.visibilityState !== "hidden";
    const timer = setInterval(() => {
      if (visible()) void load(workspaceId, () => current);
    }, pollMs);
    // Back on the tab, refresh at once instead of waiting for the next poll.
    const onVisibility = () => {
      if (visible()) void load(workspaceId, () => current);
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => { current = false; clearInterval(timer); document.removeEventListener("visibilitychange", onVisibility); };
  }, [workspaceId, view, load, pollMs]);

  return { clients, problem, load };
}

function AgentsSidebar({ sidebarCollapsed, toggleSidebarCollapsed, view, setView, onOpenAdminTab, isPlatformAdmin }: {
  sidebarCollapsed: boolean;
  toggleSidebarCollapsed: () => void;
  view: AgentsNavKey;
  setView: (view: AgentsNavKey) => void;
  onOpenAdminTab?: (tab: AdminTab) => void;
  isPlatformAdmin: boolean;
}) {
  return (
    <aside className="work-area__sidebar">
      <div className="work-area__brand">
        <div>
          <div className="work-area__eyebrow">Agent coordination</div>
          <AreaTitle area="Agents" className="work-area__title" />
        </div>
        <button
          type="button"
          className="work-area__collapse"
          onClick={toggleSidebarCollapsed}
          aria-label={sidebarCollapsed ? "Expand Agents navigation" : "Collapse Agents navigation"}
          title={sidebarCollapsed ? "Expand navigation" : "Collapse navigation"}
        >
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path d={sidebarCollapsed ? "M7 5l5 5-5 5" : "M13 5l-5 5 5 5"} />
          </svg>
        </button>
      </div>
      <AgentsAreaMenuNav activeKey={view} onSelectLocal={setView}
        onOpenTab={(tab) => onOpenAdminTab?.(tab)} showBuilder={isPlatformAdmin} />
    </aside>
  );
}

type BodyProps = {
  view: AgentsNavKey;
  setView: (view: AgentsNavKey) => void;
  workspaceId: string | null;
  projects: ProjectOption[];
  clients: ConnectedClient[] | null;
  problem: string | null;
  load: (projectId: string, isCurrent: () => boolean) => Promise<void>;
  adminLink?: (tab: AdminTab) => void;
  isPlatformAdmin: boolean;
  focus: Focus;
  boardPollMs?: number;
};

// The view chosen in the menu; every view but "install" needs a Workspace.
function AgentsAreaBody(props: BodyProps) {
  const { view, setView, workspaceId, projects, clients, problem, load, adminLink, isPlatformAdmin, focus, boardPollMs } = props;
  return view === "install" ? (
    <AgentsInstallClient workspaceId={workspaceId} />
  ) : !workspaceId ? (
    <ChooseWorkspaceLine projects={projects} purpose="to see its agents" />
  ) : view === "clients" ? (
    <>
      {problem ? <p className="work-area__error" role="alert" data-testid="agents-clients-error">{problem}</p>
        : clients === null ? <LoadingState label="agent clients" />
          : <AgentsConnectedClients clients={clients} onInstall={() => setView("install")}
              onRemove={async (client) => {
                await removeAgentPresence(client.id, workspaceId);
                await load(workspaceId, () => true);
              }} />}
      {problem || clients?.length === 0
        ? <AgentsSeatRefusal projectId={workspaceId} onOpenClassification={() => setView("classification")} />
        : null}
      {/* Every person's devices are in Admin › Platform › Devices. */}
      {adminLink ? (
        <EmptyLine text="Every person's devices are in Admin › Platform."
          action={{ label: "Open Devices", onClick: () => adminLink("platformDevices") }} testId="agents-admin-devices-link" />
      ) : null}
    </>
  ) : view === "classification" ? (
    <WorkspaceDataClassificationCard projectId={workspaceId} titled={false} onOpenPolicy={() => setView("policy")}
      onOpenMatrix={adminLink ? () => adminLink("classificationPolicy") : undefined} />
  ) : view === "policy" ? (
    <>
      <AgentsWorkspacePolicy projectId={workspaceId} onOpenAdminTab={adminLink} />
      <WorkspaceContentHandling key={workspaceId} workspaceId={workspaceId} />
      <DeviceRunsPolicyCard projectId={workspaceId} isPlatformAdmin={isPlatformAdmin} readOnly
        onEditInSettings={adminLink ? () => adminLink("projects") : undefined} />
    </>
  ) : view === "board" ? (
    <AgentsMessageBoard key={`${workspaceId}|${focus.nonce}`} projectId={workspaceId} isPlatformAdmin={isPlatformAdmin}
      focusMessageId={focus.messageId} pollMs={boardPollMs} />
  ) : (
    <>
      <AgentsClaims key={workspaceId} projectId={workspaceId} pollMs={boardPollMs} />
      <AgentsHandoffs key={`${workspaceId}|${focus.nonce}`} projectId={workspaceId} focusTakeoverId={focus.takeoverId}
        focusWorkItemId={focus.workItemId} focusClaimId={focus.handoffClaimId} pollMs={boardPollMs} />
      <AgentsHandoffPolicy key={`policy|${workspaceId}`} projectId={workspaceId} />
    </>
  );
}

// The "Agents" main-menu area (board and claims with freeze 2): the Workspace's agent clients,
// message board and claims, chosen in the same collapsible second-level menu as Work and Coding (AgentsAreaNav).
// Connected clients polls every 15 s while the page is visible and refreshes at once when it becomes visible again.
// The action-needed bell and notification links open it on an item (agentsFocus).
export function AgentsAreaWorkspace({ projects, fallbackWorkspaceId = null, isPlatformAdmin = false, onOpenAdminTab, pollMs = PRESENCE_POLL_MS,
  boardPollMs }: {
  projects: ProjectOption[];
  fallbackWorkspaceId?: string | null;
  isPlatformAdmin?: boolean;
  // Opens an admin page (the classification policy matrix, Limits & budgets); offered to platform admins only.
  // Opens an admin-shell page: the Agents builder pages of the menu, and the admin links of the Policy view.
  onOpenAdminTab?: (tab: AdminTab) => void;
  pollMs?: number;
  boardPollMs?: number;
}) {
  const [workspaceId] = useActiveWorkspace(projects, fallbackWorkspaceId);
  const [focus, setFocus] = useState<Focus>({ nonce: 0, messageId: null, takeoverId: null, workItemId: null, handoffClaimId: null });
  const [view, setView] = useState<AgentsNavKey>(() => readUrlAgentsView(window.location.search) ?? "clients");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readAgentsSidebarCollapsed);
  const activeNavItem = AGENTS_NAV_ITEMS.find((item) => item.key === view) ?? AGENTS_NAV_ITEMS[0];
  const toggleSidebarCollapsed = () => setSidebarCollapsed((current) => {
    storeAgentsSidebarCollapsed(!current);
    return !current;
  });
  useEffect(() => followAgentsFocus(setView, setFocus), []);
  const adminLink = isPlatformAdmin ? onOpenAdminTab : undefined;
  const { clients, problem, load } = usePresenceClients(workspaceId, view, pollMs);

  return (
    <main className={`work-area agents-area ${sidebarCollapsed ? "work-area--sidebar-collapsed" : ""}`} aria-label="Agents">
      <AgentsSidebar sidebarCollapsed={sidebarCollapsed} toggleSidebarCollapsed={toggleSidebarCollapsed} view={view}
        setView={setView} onOpenAdminTab={onOpenAdminTab} isPlatformAdmin={isPlatformAdmin} />

      <section className="work-area__main">
        <PageHeader eyebrow={agentsAreaGroup(view) ? `Agents · ${agentsAreaGroup(view)}` : "Agents"} title={activeNavItem.label} purpose={activeNavItem.subtitle}
          testIds={{ eyebrow: "agents-eyebrow", purpose: "agents-page-subtitle" }} />

        <div className="work-area__body">
          <AgentsAreaBody view={view} setView={setView} workspaceId={workspaceId} projects={projects} clients={clients}
            problem={problem} load={load} adminLink={adminLink} isPlatformAdmin={isPlatformAdmin} focus={focus}
            boardPollMs={boardPollMs} />
        </div>
      </section>
    </main>
  );
}
