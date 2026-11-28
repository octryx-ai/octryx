// The area rail: logo, Workspace switch, area destinations, setup progress, help, theme and the account menu.
import { Fragment, type ComponentType } from "react";
import { BrandGlyph } from "./BrandGlyph";
import { ThemeIcon } from "./ChatShellIcons";
import { resolveBranding } from "./branding";
import { DEFAULT_BRANDING } from "./defaultBranding";
import { CompanionLogoTrigger } from "./companion/CompanionHost";
import { GlobalWorkspaceSwitch } from "./workspace/GlobalWorkspaceSwitch";
import { useActiveWorkspace } from "./useActiveWorkspace";
import type { WorkspaceArea } from "./workspaceAreas";
import { useSetupProgress } from "./setup/useSetupProgress";
import { openPersonalTab } from "./devices/personalSettingsTab";
import { getWorkspaceDestinations, isDestinationActive } from "./workspaceDestinations";
import type { AdminTab } from "../admin/types/adminPanelTypes.governance";
import type { ProjectOption } from "../chatOptionTypes";
import {
  AgentsIcon, ChatIcon, CodingIcon, DevicesIcon, HelpIcon, KnowledgeIcon, ObservabilityIcon, ProfileIcon, SettingsIcon,
  WorkflowIcon, WorkIcon,
} from "./AreaRailIcons";

type Branding = {
  app_name: string;
  logo_url: string;
  logo_svg: string;
  enabled?: boolean;
};


/** A tenant brand with its own logo keeps it in the logo slot; otherwise the Octryx AI logo is shown. */
function hasCustomBrand(branding: Branding): boolean {
  const resolved = resolveBranding(branding);
  return resolved.enabled && (Boolean(resolved.logo_svg) || resolved.logo_url !== DEFAULT_BRANDING.logo_url);
}

const AREA_ICONS = {
  chat: ChatIcon, knowledge: KnowledgeIcon, work: WorkIcon, coding: CodingIcon, agents: AgentsIcon,
  workflows: WorkflowIcon, admin: SettingsIcon, operations: ObservabilityIcon, personal: DevicesIcon, help: HelpIcon,
};

type AreaRailProps = {
  activeBranding: Branding;
  activeArea: WorkspaceArea;
  brandFallbackLabel: string;
  chatTheme: "dark" | "light";
  currentUserIsAdmin: boolean;
  currentUserCanReadWork: boolean;
  currentUserEmail: string;
  currentUserName: string;
  currentUserId?: string | null;
  // The one Workspace switch of the app sits at the head of the rail.
  projects?: ProjectOption[];
  fallbackWorkspaceId?: string | null;
  openSettingsTab: (
    tab: AdminTab,
    area?: Exclude<WorkspaceArea, "chat" | "work">,
  ) => void;
  onOpenHelp: () => void;
  profileDropdownOpen: boolean;
  setActiveArea: (value: WorkspaceArea) => void;
  setChatTheme: (value: "dark" | "light") => void;
  setProfileDropdownOpen: (
    value: boolean | ((value: boolean) => boolean),
  ) => void;
};

type RailMenuProps = Pick<
  AreaRailProps,
  "currentUserIsAdmin" | "currentUserEmail" | "openSettingsTab" | "onOpenHelp" | "setActiveArea" | "setProfileDropdownOpen"
>;

function RailMenuItem({ icon: Icon, label, onClick }: { icon: ComponentType; label: string; onClick: () => void }) {
  return (
    <button type="button" className="profile-dropdown__item" onClick={onClick}>
      <Icon />
      <span>{label}</span>
    </button>
  );
}

function RailAccountMenu({
  currentUserIsAdmin, currentUserEmail, openSettingsTab, onOpenHelp, setActiveArea, setProfileDropdownOpen,
}: RailMenuProps) {
  const close = (then: () => void) => () => {
    setProfileDropdownOpen(false);
    then();
  };
  const openPersonal = (tab: "profile" | "devices") => close(() => {
    openPersonalTab(tab);
    setActiveArea("personal");
  });
  return (
    <div
      className="profile-dropdown profile-dropdown--rail"
      onClick={(event) => event.stopPropagation()}
    >
      <div className="profile-dropdown__header">
        <div className="profile-dropdown__email">{currentUserEmail}</div>
        <div className="profile-dropdown__label">Personal account</div>
      </div>
      <div className="profile-dropdown__divider" />
      {/* One clearly named entry per destination; no placeholder items
          without a working target. Profile holds the linked accounts,
          My settings Devices;
          language and rate limits have no personal page yet. */}
      <RailMenuItem icon={ProfileIcon} label="Profile" onClick={openPersonal("profile")} />
      <RailMenuItem icon={DevicesIcon} label="My settings" onClick={openPersonal("devices")} />
      {currentUserIsAdmin ? (
        <RailMenuItem icon={SettingsIcon} label="Platform settings"
          onClick={close(() => openSettingsTab("adminProblems", "admin"))} />
      ) : null}
      {currentUserIsAdmin ? (
        <RailMenuItem icon={ObservabilityIcon} label="Usage & costs"
          onClick={close(() => openSettingsTab("usage", "operations"))} />
      ) : null}
      <RailMenuItem icon={HelpIcon} label="Setup guide" onClick={close(() => setActiveArea("help"))} />
      <RailMenuItem icon={HelpIcon} label="Help for this page" onClick={close(onOpenHelp)} />
      <div className="profile-dropdown__divider" />
      <button
        type="button"
        className="profile-dropdown__item profile-dropdown__item--danger"
        onClick={() => {
          window.location.href = "/chat/logout";
        }}
      >
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <path d="M7.5 10h9M13.5 7l3 3-3 3" />
          <path d="M12 4H5.5A1.5 1.5 0 0 0 4 5.5v9A1.5 1.5 0 0 0 5.5 16H12" />
        </svg>
        <span>Log out</span>
      </button>
    </div>
  );
}

function RailDestinations({
  currentUserIsAdmin, currentUserCanReadWork, activeArea, openSettingsTab, setActiveArea,
}: Pick<AreaRailProps, "currentUserIsAdmin" | "currentUserCanReadWork" | "activeArea" | "openSettingsTab" | "setActiveArea">) {
  return (
    <>
      {getWorkspaceDestinations(currentUserIsAdmin, currentUserCanReadWork).map((item) => {
        const Icon = AREA_ICONS[item.area];
        return (
          <Fragment key={item.area}>
            {item.area === "operations" ? (
              <div className="area-rail__divider" />
            ) : null}
            <button type="button"
              className={`area-rail__btn ${isDestinationActive(item, activeArea) ? "is-active" : ""}`}
              data-tooltip={item.label} aria-label={item.label}
              aria-current={isDestinationActive(item, activeArea) ? "page" : undefined}
              onClick={() => {
                if (item.adminTab) openSettingsTab(item.adminTab);
                else setActiveArea(item.area);
              }}>
              <Icon />
            </button>
          </Fragment>
        );
      })}
    </>
  );
}

function RailFooter({
  chatTheme, currentUserName, onOpenHelp, profileDropdownOpen, setChatTheme, setProfileDropdownOpen, ...rest
}: AreaRailProps) {
  const userInitial = currentUserName[0]?.toUpperCase() || "U";
  const nextTheme = chatTheme === "dark" ? "light" : "dark";
  return (
    <>
      <button
        type="button"
        className="area-rail__theme"
        data-tooltip="Help"
        aria-label="Open page help"
        onClick={onOpenHelp}
      >
        <HelpIcon />
      </button>

      <button
        type="button"
        className="area-rail__theme"
        data-tooltip={`Switch to ${nextTheme} theme`}
        aria-label={`Switch to ${nextTheme} theme`}
        onClick={() => setChatTheme(nextTheme)}
      >
        <ThemeIcon theme={chatTheme} />
      </button>

      <div className="area-rail__account-shell">
        <button
          type="button"
          className={`area-rail__btn area-rail__account ${profileDropdownOpen ? "area-rail__account--open" : ""}`}
          data-tooltip={currentUserName || "Account"}
          aria-label="Account"
          aria-expanded={profileDropdownOpen}
          onClick={() => setProfileDropdownOpen((value) => !value)}
        >
          <span>{userInitial}</span>
        </button>
        {profileDropdownOpen ? (
          <RailAccountMenu {...rest} onOpenHelp={onOpenHelp} setProfileDropdownOpen={setProfileDropdownOpen} />
        ) : null}
      </div>
    </>
  );
}

export function AreaRail(props: AreaRailProps) {
  const {
    activeBranding, brandFallbackLabel, currentUserIsAdmin, currentUserId, projects = [], fallbackWorkspaceId = null,
    setActiveArea,
  } = props;
  // The setup count of the Workspace this page shows, resolved like the Workspace switch and the setup guide.
  const [shownWorkspaceId] = useActiveWorkspace(projects, fallbackWorkspaceId);
  const setupProgress = useSetupProgress(currentUserIsAdmin, currentUserId, shownWorkspaceId || null);
  // The count includes the shown Workspace's own steps, so it changes with the Workspace; the tooltip names it.
  const setupWorkspace = projects.find((project) => project.id === shownWorkspaceId)?.name;
  const setupTip = `${setupProgress}${setupWorkspace ? ` for ${setupWorkspace}` : ""} · Open the setup guide`;

  return (
    <nav className="area-rail" aria-label="Workspace areas">
      {/* The logo is Octryx (the companion): a click opens its panel; Chat stays the first destination below. */}
      <CompanionLogoTrigger className="area-rail__logo"
        glyph={hasCustomBrand(activeBranding)
          ? <BrandGlyph branding={activeBranding} fallbackLabel={brandFallbackLabel} /> : undefined} />
      <GlobalWorkspaceSwitch projects={projects} fallbackWorkspaceId={fallbackWorkspaceId} allowGlobal={currentUserIsAdmin} />
      <div className="area-rail__divider" />
      <RailDestinations {...props} />
      <div className="area-rail__spacer" />
      {/* Octryx (the logo above) replaces the action-needed bell; the setup progress stays in the rail. */}
      {setupProgress ? (
        <button type="button" className="area-rail__btn area-rail__setup" data-testid="rail-setup-progress"
          aria-label={setupTip} data-tooltip={setupTip}
          onClick={() => setActiveArea("help")}>
          {/* Visible label, not only a tooltip; gone once every required step is done. */}
          <span className="area-rail__setup-label">Setup</span>
          <span>{/(\d+ of \d+)/.exec(setupProgress)?.[1].replace(" of ", "/") ?? ""}</span>
        </button>
      ) : null}
      <div className="area-rail__divider" />

      <RailFooter {...props} />
    </nav>
  );
}
