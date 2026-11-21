import { useCallback, useState } from "react";
import { canManageWorkWith, canReadWorkWith } from "./work/workAccess";
import { areaForRole } from "./workspaceDestinations";

import type { ApprovalSummary } from "../chatDecisionTypes";
import type { ChatState } from "../types";
import { BootstrapUnavailable } from "./BootstrapUnavailable";
import { AdminAreaWorkspace } from "./AdminAreaWorkspace";
import { AreaRail } from "./AreaRail";
import { CompactAreaMenu } from "./CompactAreaMenu";
import { AgentsAreaWorkspace } from "./agents/AgentsAreaWorkspace";
import { PageHelpDrawer } from "./PageHelpDrawer";
import { useHelpPage, usePageHelp } from "../help/usePageHelp";
import { AppContainerOverlays } from "./AppContainerOverlays";
import { CodingWorkspaceEntry } from "./coding/CodingWorkspaceEntry";
import { WorkAreaWorkspace } from "./work/WorkAreaWorkspace";
import { SpecStudioPage } from "./specStudio/SpecStudioPage";
import { SpecStudioRender } from "./specStudio/SpecStudioRender";
import { specStudioAddress } from "./specStudio/specStudioAddress";
import { PersonalSettingsWorkspace } from "./devices/PersonalSettingsWorkspace";
import { SetupGuidePage } from "./setup/SetupGuidePage";
import { CompanionHost } from "./companion/CompanionHost";
import { AdminReturnFrame } from "./navigation/AdminReturnFrame";
import { currentAdminReturn } from "./navigation/adminReturn";
import { ChatAppArea } from "./ChatAppArea";

function getBrandFallbackLabel(appName: string) {
  return (
    appName
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase() || "")
      .join("")
      .slice(0, 2) || "O"
  );
}
// The roles of the signed-in user: admin, and whether Work may be managed or read.
function userAccess(chatState: ChatState | null) {
  const currentUserIsAdmin =
    chatState?.currentUser.roles.some(
      (role: string) => role.trim().toLowerCase() === "admin",
    ) ?? false;
  const roleNames = (chatState?.currentUser.roles || []).map((role: string) =>
    role.trim().toLowerCase(),
  );
  const currentUserCanManageWork = canManageWorkWith(roleNames);
  // Every Workspace member reads Work; the rail's Work opens the Work pages for them too.
  const currentUserCanReadWork = canReadWorkWith(roleNames, chatState?.projects?.length ?? 0);
  return { currentUserIsAdmin, roleNames, currentUserCanManageWork, currentUserCanReadWork };
}

// The page of the shown area: Work (or its Spec Studio), Agents, Personal, Help, Coding, an admin area, or the chat.
function AppAreaContent({ props, shownArea, studioAddress, pageVisit, access }: {
  props: any;
  shownArea: ReturnType<typeof areaForRole>;
  studioAddress: ReturnType<typeof specStudioAddress>;
  pageVisit: number;
  access: ReturnType<typeof userAccess>;
}) {
  const {
    chatState, setActiveArea, adminPanelInitialTab, openSettingsTab, activeBranding, currentUserName, onApprovalStateChanged,
    loadState,
  } = props;
  const { currentUserIsAdmin, roleNames, currentUserCanManageWork } = access;
  const activeAdminArea =
    shownArea === "chat" || shownArea === "work" || shownArea === "coding" || shownArea === "agents" ||
    shownArea === "personal" || shownArea === "help"
      ? null : shownArea;
  return shownArea === "work" ? (
    studioAddress ? (
      <SpecStudioPage runId={studioAddress.runId} onBack={() => {
        if (window.history.length > 1) window.history.back();
        else window.location.assign("/chat?area=work&work_view=runs");
      }} />
    ) : <AdminReturnFrame target={currentAdminReturn()} onReturn={openSettingsTab}>
      <WorkAreaWorkspace key={`work-${pageVisit}`} projects={chatState?.projects ?? []} initialWorkspaceId={chatState?.selectedProjectId ?? null}
        onOpenAdminTab={openSettingsTab} onOpenArea={setActiveArea} canManageWork={currentUserCanManageWork}
        viewer={{ id: chatState?.currentUser?.id ?? "", name: currentUserName || chatState?.currentUser?.username || "", role: roleNames[0] ?? "member" }} />
    </AdminReturnFrame>
  ) : shownArea === "agents" ? (
    <AgentsAreaWorkspace projects={chatState?.projects ?? []} fallbackWorkspaceId={chatState?.selectedProjectId ?? null}
      isPlatformAdmin={currentUserIsAdmin} onOpenAdminTab={openSettingsTab} />
  ) : shownArea === "personal" ? (
    <PersonalSettingsWorkspace projects={chatState?.projects ?? []} fallbackWorkspaceId={chatState?.selectedProjectId ?? null} />
  ) : shownArea === "help" ? (
    <SetupGuidePage projects={chatState?.projects ?? []} fallbackWorkspaceId={chatState?.selectedProjectId ?? null}
      userId={chatState?.currentUser?.id} isAdmin={currentUserIsAdmin} />
  ) : shownArea === "coding" ? (
    <AdminReturnFrame target={currentAdminReturn()} onReturn={openSettingsTab}>
      <CodingWorkspaceEntry key={`coding-${pageVisit}`} projects={chatState.projects} initialWorkspaceId={chatState.selectedProjectId} canManageWork={currentUserCanManageWork}
        isPlatformAdmin={currentUserIsAdmin} onOpenAdminTab={openSettingsTab} onOpenArea={setActiveArea} />
    </AdminReturnFrame>
  ) : activeAdminArea ? (
    <AdminAreaWorkspace
      area={activeAdminArea}
      activeBranding={activeBranding}
      adminPanelInitialTab={adminPanelInitialTab}
      chatState={chatState}
      currentUserId={chatState?.currentUser?.id}
      isAdmin={currentUserIsAdmin}
      onOpenAdminTab={openSettingsTab}
      loadState={loadState}
      onApprovalStateChanged={onApprovalStateChanged}
      projects={chatState?.projects ?? []}
      onOpenArea={setActiveArea}
    />
  ) : (
    <ChatAppArea {...props} />
  );
}

// The compact area menu and the area rail with the brand, the user and the theme.
function AppShellNavigation({ props, shownArea, access, openAreaPage, onOpenHelp }: {
  props: any;
  shownArea: ReturnType<typeof areaForRole>;
  access: ReturnType<typeof userAccess>;
  openAreaPage: (area: any, params?: Record<string, string>) => void;
  onOpenHelp: () => void;
}) {
  const {
    chatState, setActiveArea, openSettingsTab, activeBranding, currentUserName, currentUserEmail, profileDropdownOpen,
    setProfileDropdownOpen, chatTheme, setChatTheme,
  } = props;
  const { currentUserIsAdmin, currentUserCanManageWork, currentUserCanReadWork } = access;
  const brandFallbackLabel = getBrandFallbackLabel(activeBranding.app_name);
  return (
    <>
      <CompactAreaMenu activeArea={shownArea} isAdmin={currentUserIsAdmin}
        canReadWork={currentUserCanReadWork} canManageWork={currentUserCanManageWork} onSelectArea={openAreaPage}
        onSelectAdminTab={openSettingsTab}
        projects={chatState?.projects} fallbackWorkspaceId={chatState?.selectedProjectId} />
      <AreaRail
        activeBranding={activeBranding}
        activeArea={shownArea}
        brandFallbackLabel={brandFallbackLabel}
        chatTheme={chatTheme}
        currentUserIsAdmin={currentUserIsAdmin}
        currentUserCanReadWork={currentUserCanReadWork}
        currentUserEmail={currentUserEmail}
        currentUserName={currentUserName}
        currentUserId={chatState?.currentUser?.id}
        projects={chatState?.projects} fallbackWorkspaceId={chatState?.selectedProjectId}
        onOpenHelp={onOpenHelp}
        openSettingsTab={openSettingsTab}
        profileDropdownOpen={profileDropdownOpen}
        setActiveArea={setActiveArea}
        setChatTheme={setChatTheme}
        setProfileDropdownOpen={setProfileDropdownOpen}
      />
    </>
  );
}

// The trace and preview overlays and, when open, the page help drawer.
function AppShellOverlays({ props, shownArea, currentUserIsAdmin, helpPage, pageHelpOpen, setPageHelpOpen }: {
  props: any;
  shownArea: ReturnType<typeof areaForRole>;
  currentUserIsAdmin: boolean;
  helpPage: ReturnType<typeof useHelpPage>;
  pageHelpOpen: boolean;
  setPageHelpOpen: (open: boolean) => void;
}) {
  const {
    chatState, traceOpen, setTraceOpen, assistantRetryPromptByMessageId, handleRetryFromToolEvent, setPreviewArtifact,
    composerDisabled, previewArtifact, openSettingsTab, setActiveArea,
  } = props;
  return (
    <>
      <AppContainerOverlays
        chatState={chatState}
        traceOpen={traceOpen}
        setTraceOpen={setTraceOpen}
        assistantRetryPromptByMessageId={assistantRetryPromptByMessageId}
        handleRetryFromToolEvent={handleRetryFromToolEvent}
        setPreviewArtifact={setPreviewArtifact}
        composerDisabled={composerDisabled}
        previewArtifact={previewArtifact}
        canInspectSetup={currentUserIsAdmin} />
      {pageHelpOpen ? (
        <PageHelpDrawer area={shownArea} page={helpPage} onClose={() => setPageHelpOpen(false)}
          onNavigate={(target) => {
            if (target.tab && target.area !== "help") openSettingsTab(target.tab); else setActiveArea(target.area);
          }} />
      ) : null}
    </>
  );
}

export function AppContainerView(props: any) {
  const { loading, chatState, activeArea, setActiveArea, handleThreadSelect, error, loadState } = props;
  const [pageHelpOpen, setPageHelpOpen] = usePageHelp();
  const helpPage = useHelpPage(activeArea);
  const retryBootstrap = useCallback(() => void loadState(window.location.search, { silent: true }), [loadState]);
  // The Work and Coding pages read their page from the address when they open; a page chosen in the compact menu
  // while one of them is open reopens it on that page.
  const [pageVisit, setPageVisit] = useState(0);
  const openAreaPage = (area: Parameters<typeof setActiveArea>[0], params?: Record<string, string>) => {
    setActiveArea(area, params);
    if (params) setPageVisit((visit) => visit + 1);
  };

  if (!chatState && loading) {
    return (
      <div className="chat-loading">
        <div className="chat-loading__orb" />
        <div>Loading chat workspace…</div>
      </div>
    );
  }

  if (!chatState && error) {
    return <BootstrapUnavailable message={error} onRetry={retryBootstrap} />;
  }

  const access = userAccess(chatState);
  const { currentUserIsAdmin } = access;
  // The Spec Studio is a full-width Work view; with `render=` only the bare mock (the review baseline image). Both
  // render only here, after the bootstrap, so they need the login like every page.
  // A member never lands on an admin area it cannot open (a link): it sees the area its rail offers.
  const shownArea = areaForRole(activeArea, currentUserIsAdmin);
  const studioAddress = shownArea === "work" ? specStudioAddress(window.location.search) : null;
  if (studioAddress?.render) return <SpecStudioRender address={studioAddress} />;

  return (
    <CompanionHost userId={chatState?.currentUser?.id} onOpenAgents={() => setActiveArea("agents")} isAdmin={currentUserIsAdmin}
      onOpenSession={(id) => { setActiveArea("chat"); void handleThreadSelect({ id }); }}>
    <div className={`app-shell${pageHelpOpen ? " app-shell--help-open" : ""}`}>
      <AppShellNavigation props={props} shownArea={shownArea} access={access} openAreaPage={openAreaPage}
        onOpenHelp={() => setPageHelpOpen(true)} />

      <AppAreaContent props={props} shownArea={shownArea} studioAddress={studioAddress} pageVisit={pageVisit}
        access={access} />
      <AppShellOverlays props={props} shownArea={shownArea} currentUserIsAdmin={currentUserIsAdmin} pageHelpOpen={pageHelpOpen}
        helpPage={helpPage} setPageHelpOpen={setPageHelpOpen} />
    </div>
    </CompanionHost>
  );
}
