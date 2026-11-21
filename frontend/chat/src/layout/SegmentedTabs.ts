import { createElement, useEffect, useRef, type KeyboardEvent } from "react";

// The one tab style (design system): segments, for page views (Open | Merged | All) and for the tabs inside a side
// panel. role=tablist with roving focus: arrow keys move and select, Home/End jump. No pill groups anywhere else.

// testId: the tab button's own data-testid (pages whose tests click one tab).
export type SegmentedTab = { key: string; label: string; count?: number; disabled?: boolean; testId?: string };

export type SegmentedTabsProps = {
  tabs: SegmentedTab[];
  value: string;
  onChange: (key: string) => void;
  // Accessible name of the group ("Pull request views").
  label: string;
  // id prefix: a tab is `${idPrefix}-tab-${key}` and controls `${idPrefix}-panel-${key}`.
  idPrefix?: string;
  size?: "regular" | "small";
  testId?: string;
};

export function nextTabKey(tabs: SegmentedTab[], current: string, key: string): string | null {
  const enabled = tabs.filter((tab) => !tab.disabled);
  if (!enabled.length) return null;
  const index = Math.max(0, enabled.findIndex((tab) => tab.key === current));
  if (key === "ArrowRight" || key === "ArrowDown") return enabled[(index + 1) % enabled.length].key;
  if (key === "ArrowLeft" || key === "ArrowUp") return enabled[(index - 1 + enabled.length) % enabled.length].key;
  if (key === "Home") return enabled[0].key;
  if (key === "End") return enabled[enabled.length - 1].key;
  return null;
}

/**
 * The scroll position that shows the selected segment inside a row that scrolls sideways (a phone, an open help
 * panel): unchanged when it is fully visible, else just enough to show it with a small margin. Pure, for tests.
 */
export function scrollToShow(scrollLeft: number, viewWidth: number, tabLeft: number, tabWidth: number, margin = 16): number {
  if (tabLeft < scrollLeft) return Math.max(0, tabLeft - margin);
  if (tabLeft + tabWidth > scrollLeft + viewWidth) return Math.max(0, tabLeft + tabWidth - viewWidth + margin);
  return scrollLeft;
}

export function SegmentedTabs({ tabs, value, onChange, label, idPrefix = "ds-tabs", size = "regular", testId }: SegmentedTabsProps) {
  const refs = useRef(new Map<string, HTMLButtonElement | null>());
  const listRef = useRef<HTMLDivElement | null>(null);
  // On a narrow screen the selected tab can sit off-screen in the sideways-scrolling row. The row scrolls the selected segment into view when it is chosen or shown.
  useEffect(() => {
    const list = listRef.current;
    const tab = refs.current.get(value);
    if (!list || !tab || typeof list.scrollWidth !== "number" || list.scrollWidth <= list.clientWidth) return;
    const tabBox = tab.getBoundingClientRect();
    const tabLeft = tabBox.left - list.getBoundingClientRect().left + list.scrollLeft;
    const left = scrollToShow(list.scrollLeft, list.clientWidth, tabLeft, tabBox.width);
    if (left !== list.scrollLeft) list.scrollLeft = left;
  }, [value]);
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const next = nextTabKey(tabs, value, event.key);
    if (!next) return;
    event.preventDefault();
    onChange(next);
    refs.current.get(next)?.focus?.();
  };
  return createElement(
    "div",
    { ref: listRef, className: `ds-segments ds-segments--${size}`, role: "tablist", "aria-label": label, onKeyDown, "data-testid": testId },
    ...tabs.map((tab) => {
      const selected = tab.key === value;
      return createElement(
        "button",
        {
          key: tab.key,
          ref: (node: HTMLButtonElement | null) => { refs.current.set(tab.key, node); },
          type: "button",
          role: "tab",
          id: `${idPrefix}-tab-${tab.key}`,
          "aria-selected": selected,
          "aria-controls": `${idPrefix}-panel-${tab.key}`,
          tabIndex: selected ? 0 : -1,
          disabled: tab.disabled,
          className: `ds-segments__tab${selected ? " is-selected" : ""}`,
          "data-testid": tab.testId,
          onClick: () => onChange(tab.key),
        },
        tab.label,
        typeof tab.count === "number" ? createElement("span", { className: "ds-segments__count" }, String(tab.count)) : null,
      );
    }),
  );
}
