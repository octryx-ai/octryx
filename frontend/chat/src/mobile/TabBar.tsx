// The phone's bottom navigation (one-hand use): the app's main areas in thumb reach, the active one in the accent,
// a count where something waits for the person. Detail pages (a chat, a run) cover it and go back with ‹.

import { Icon, type IconName } from "./icons";

export type TabKey = "home" | "chats" | "runs" | "work" | "more";

export type TabItem = { key: TabKey; label: string; icon: IconName; badge?: number };

export function TabBar({ tabs, active, onSelect }: { tabs: TabItem[]; active: TabKey; onSelect: (tab: TabKey) => void }) {
  return (
    <nav className="m-tabbar" aria-label="Main">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          className="m-tab"
          aria-current={tab.key === active ? "page" : undefined}
          data-testid={`m-tab-${tab.key}`}
          onClick={() => onSelect(tab.key)}
        >
          <span className="m-tab-icon">
            <Icon name={tab.icon} />
            {tab.badge ? (
              <span className="m-tab-badge" aria-label={`${tab.badge} waiting for you`}>
                {tab.badge > 99 ? "99+" : tab.badge}
              </span>
            ) : null}
          </span>
          <span className="m-tab-label">{tab.label}</span>
        </button>
      ))}
    </nav>
  );
}
