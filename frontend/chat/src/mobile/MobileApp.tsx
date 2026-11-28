// Octryx Mobile, the Home Screen app: pairing page,
// sign-in with the phone's own credential, then the app's areas in a bottom tab bar (Home, Chats, Runs, Work, More)
// with one Workspace switch for all of them. Detail pages (a chat, a run, a Work item, a new chat) open above the tabs.

import { ConfirmPage } from "./ConfirmPage";
import { ConnectPage } from "./ConnectPage";
import { newChatWorkspace } from "./mobileWorkspace";
import { detailPage } from "./mobileDetailPages";
import { useMobileItemLinks, useMobileLoad, useMobileSignIn } from "./mobileAppSession";
import { type MobileAppState, useMobileAppState, useShownLists } from "./mobileAppState";
import { MobileTabScreen } from "./MobileTabScreen";
import { phoneFetch } from "./PluginPage";
import { usePluginSlots } from "../admin/components/plugins/usePluginSlots";
import { slotsOf, type PluginSlotEntry } from "../admin/components/plugins/pluginUiModel";
import { OctryxMark } from "./OctryxMark";
import { PairPage } from "./PairPage";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";

type Openers = ReturnType<typeof useMobileItemLinks>;
type Shown = ReturnType<typeof useShownLists>;

function TabScreen({ state, shown, openers, roleWorkspaceName, phonePages, chooseWorkspace }: {
  state: MobileAppState;
  shown: Shown;
  openers: Openers;
  roleWorkspaceName: string;
  phonePages: PluginSlotEntry[];
  chooseWorkspace: (id: string) => void;
}) {
  const { workspace, projects } = state;
  const switcher = <WorkspaceSwitcher workspace={workspace} workspaces={projects} onChange={chooseWorkspace} />;
  return (
    <MobileTabScreen
      tab={state.tab}
      setTab={state.setTab}
      switcher={switcher}
      workspace={workspace}
      workspaceNames={state.workspaceNames}
      needs={shown.needs}
      shownApprovals={shown.shownApprovals}
      shownThreads={shown.shownThreads}
      shownCases={shown.shownCases}
      sessions={state.sessions}
      liveSessions={state.liveSessions}
      localSessions={state.localSessions}
      usage={state.usage}
      loading={state.loading}
      error={state.error}
      devices={state.devices}
      runRows={state.runRows}
      openTasks={state.openTasks}
      myTasks={state.myTasks}
      session={state.session}
      roleWorkspaceName={roleWorkspaceName}
      phonePages={phonePages}
      workMine={state.workMine}
      setWorkMine={state.setWorkMine}
      startingRun={state.startingRun}
      setStartingRun={state.setStartingRun}
      setPhase={state.setPhase}
      openPage={state.openPage}
      openItem={openers.openItem}
      takeOver={openers.takeOver}
      openThread={openers.openThread}
      openLocal={openers.openLocal}
    />
  );
}

export function MobileApp() {
  const state = useMobileAppState();
  const { phase, session, workspace, projects, workspaceNames, setPhase } = state;
  // Plugin phone pages (plugins contract §4) of the chosen Workspace, else the default one (as a new chat).
  const pluginWorkspace = newChatWorkspace(workspace, projects);
  // Re-read with every session renewal (app back in front, every few minutes): a list refused or empty once
  // (before a deploy, or before a plugin was installed) must not stay empty while the app stays open.
  const pluginSlots = usePluginSlots(phase === "ready" ? pluginWorkspace || null : null, phoneFetch, session);
  const phonePages = slotsOf(pluginSlots.entries, "phone");
  const path = window.location.pathname.replace(/\/+$/, "");
  const pairing = path === "/m/pair";
  // The Mac's browser confirms a phone here (web session only); no phone session runs on this page.
  const confirming = path === "/m/confirm";
  const { chooseWorkspace, signIn } = useMobileSignIn(state, pairing, confirming);
  const load = useMobileLoad(state);
  const shown = useShownLists(state);
  const openers = useMobileItemLinks(state, load);

  if (confirming) return <ConfirmPage />;
  if (pairing) return <PairPage onClaim={(claim) => void signIn(claim).catch(() => setPhase("signedOut"))} />;
  if (phase === "loading")
    return (
      <main className="m-center">
        <OctryxMark size={56} />
      </main>
    );
  if (phase === "signedOut") return <ConnectPage onClaim={signIn} />;

  // My role is per Workspace: the chosen one, else the person's default (as a new chat).
  const roleWorkspace = newChatWorkspace(workspace, projects);
  const roleWorkspaceName = workspaceNames[roleWorkspace] ?? "";
  const openDetail = detailPage({
    detail: state.detail, back: state.back, openPage: state.openPage, replacePage: state.replacePage, load, projects,
    workspace, workspaceNames, cases: state.cases, liveSessions: state.liveSessions, chooseWorkspace, roleWorkspace,
    roleWorkspaceName, phonePages, session, pluginWorkspace,
  });
  if (openDetail) return openDetail;
  return (
    <TabScreen state={state} shown={shown} openers={openers} roleWorkspaceName={roleWorkspaceName}
      phonePages={phonePages} chooseWorkspace={chooseWorkspace} />
  );
}
