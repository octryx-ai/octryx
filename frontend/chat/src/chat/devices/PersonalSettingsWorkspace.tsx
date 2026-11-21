import { useEffect, useState } from "react";

import type { ProjectOption } from "../../chatOptionTypes";

import { writeAreaTabToUrl } from "../areaNavigation";
import { MyNotificationsPage } from "../notifications/MyNotificationsPage";
import { ProfilePage } from "../profile/ProfilePage";
import { MyDevicesPage } from "./MyDevicesPage";
import { onPersonalTab, readPersonalTab, takePendingPersonalTab } from "./personalSettingsTab";
import type { PersonalTab } from "./personalSettingsTab";
import "./devices.css";

// My settings: the personal settings of the signed-in user, opened from the account menu: Profile
// (linked accounts), Devices and Notifications (alerts about run and device problems). No placeholder entries without a working target.
function DevicesIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="4" y="5" width="16" height="10" rx="1.5" />
      <path d="M2 19h20" />
    </svg>
  );
}

function ProfileIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 20c1.2-3.6 3.8-5.5 7-5.5s5.8 1.9 7 5.5" />
    </svg>
  );
}

function BellIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z" />
      <path d="M10 20.5a2 2 0 0 0 4 0" />
    </svg>
  );
}

const TABS: { key: PersonalTab; label: string; Icon: () => JSX.Element }[] = [
  { key: "profile", label: "Profile", Icon: ProfileIcon },
  { key: "devices", label: "Devices", Icon: DevicesIcon },
  { key: "notifications", label: "Notifications", Icon: BellIcon },
];

const PAGES: Record<Exclude<PersonalTab, "profile">, (props: Record<string, never>) => JSX.Element> = {
  devices: MyDevicesPage,
  notifications: MyNotificationsPage,
};

// `projects` and `fallbackWorkspaceId`: the Profile's coding engine choice is per Workspace in focus.
export function PersonalSettingsWorkspace({ projects = [], fallbackWorkspaceId = null }: {
  projects?: ProjectOption[];
  fallbackWorkspaceId?: string | null;
} = {}) {
  const [tab, setTab] = useState<PersonalTab>(() => takePendingPersonalTab() ?? readPersonalTab(window.location.search));

  useEffect(() => onPersonalTab(setTab), []);
  useEffect(() => {
    writeAreaTabToUrl(tab === "devices" ? null : tab);
  }, [tab]);

  const Page = tab === "profile" ? null : PAGES[tab];
  return (
    <main className="admin-area-workspace" aria-label="My settings">
      <div className="admin-panel admin-panel--workspace admin-panel--area admin-panel--personal">
        <aside className="admin-panel__sidebar">
          <div className="admin-panel__sidebar-logo">
            <div className="admin-panel__sidebar-brand">
              <span className="admin-panel__sidebar-title">Personal</span>
              <span className="admin-panel__sidebar-subtitle">My settings</span>
            </div>
          </div>
          <section className="admin-panel__tab-group">
            <div className="admin-panel__tab-group-label">Account</div>
            <div className="admin-panel__tab-tree">
              {TABS.map(({ key, label, Icon }) => (
                <button key={key} type="button"
                  className={`admin-panel__tab ${tab === key ? "admin-panel__tab--active" : ""}`}
                  aria-current={tab === key ? "page" : undefined} onClick={() => setTab(key)}>
                  <Icon />
                  <span className="admin-panel__tab-label">{label}</span>
                </button>
              ))}
            </div>
          </section>
        </aside>
        {Page ? <Page /> : <ProfilePage projects={projects} fallbackWorkspaceId={fallbackWorkspaceId} />}
      </div>
    </main>
  );
}
