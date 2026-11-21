import { createElement } from "react";
import { SegmentedTabs } from "../../layout/SegmentedTabs";
import { isAdminTabRefEnabled, listAdminAreaTabRefs, type AdminPlatformFeatures } from "../config/adminPanelAreas";
import { locateAdminPage, type AdminEntryView, type AdminViewPointer } from "../config/adminEntries";
import { requestAdminSection } from "../config/adminPageSection";
import type { AdminTab } from "../types/adminPanelTypes.governance";

// The views of an Admin entry as segments at the top of its page; a view with several pages gets a
// second, small row (never a third). External views (Repositories, Jira write-back) open their
// component through `onExternal`.
// Plain .ts with createElement so the unit-test loaders can import it.

export type AdminEntryTabsProps = {
  tab: AdminTab;
  setTab: (tab: AdminTab) => void;
  isAdmin?: boolean;
  features?: AdminPlatformFeatures;
  onExternal?: (key: string) => void;
  // External keys the shell can open; an external view without one is left out.
  externalKeys?: string[];
};

function visiblePages(view: AdminEntryView, allowed: Set<AdminTab>) {
  return (view.pages ?? []).filter((page) => allowed.has(page.tab));
}

export function AdminEntryTabs({ tab, setTab, isAdmin = true, features = {}, onExternal, externalKeys = [] }: AdminEntryTabsProps) {
  const location = locateAdminPage(tab);
  if (!location || location.entry.views.length === 0) return null;
  const allowed = new Set(
    listAdminAreaTabRefs("admin", isAdmin).filter((ref) => isAdminTabRefEnabled(ref, features)).map((ref) => ref.id),
  );
  const views = location.entry.views.filter((view) =>
    view.external ? externalKeys.includes(view.external) : visiblePages(view, allowed).length > 0,
  );
  const current = location.view;
  const subPages = current ? visiblePages(current, allowed) : [];
  const openView = (key: string) => {
    const target = views.find((view) => view.key === key);
    if (!target) return;
    if (target.external) onExternal?.(target.external);
    else {
      const first = visiblePages(target, allowed)[0];
      if (first) setTab(first.tab);
    }
  };
  return createElement(
    "div",
    { className: "admin-entry-tabs", "data-testid": "admin-entry-tabs" },
    createElement(
      "div",
      { className: "admin-entry-tabs__row" },
      views.length > 1
        ? createElement(SegmentedTabs, {
          tabs: views.map((view) => ({ key: view.key, label: view.label })),
          value: current?.key ?? "",
          onChange: openView,
          label: `${location.entry.label} views`,
          idPrefix: `admin-entry-${location.entry.key}`,
          testId: "admin-entry-views",
        })
        : null,
    ),
    subPages.length > 1
      ? createElement(SegmentedTabs, {
        tabs: subPages.map((page) => ({ key: page.tab, label: page.label })),
        value: location.page?.tab ?? "",
        onChange: (key: string) => setTab(key as AdminTab),
        label: `${current?.label ?? ""} pages`,
        idPrefix: `admin-entry-${location.entry.key}-${current?.key ?? ""}`,
        size: "small",
        testId: "admin-entry-pages",
      })
      : null,
    current?.pointers?.length
      ? createElement(
        "div",
        { className: "admin-entry-tabs__row", "data-testid": "admin-entry-pointers" },
        current.pointers.map((pointer) => createElement(PointerLink, { key: pointer.label, pointer, setTab })),
      )
      : null,
  );
}

// A setting that lives in another entry: the link opens its home (and its register), the setting is not repeated.
function PointerLink({ pointer, setTab }: { pointer: AdminViewPointer; setTab: (tab: AdminTab) => void }) {
  const open = () => {
    if (pointer.section) requestAdminSection(pointer.tab, pointer.section);
    setTab(pointer.tab);
  };
  return createElement(
    "button",
    { type: "button", className: "admin-panel__action-btn", onClick: open, "data-testid": "admin-entry-pointer" },
    pointer.label,
  );
}
