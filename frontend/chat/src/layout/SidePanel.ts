import { createElement, useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from "react";

import { SegmentedTabs, type SegmentedTabsProps } from "./SegmentedTabs";

// The one detail surface of the design system (product inventory): a sheet laid over the
// dimmed list, with the title, "Open as page", ✕, optional segmented tabs, the content and footer actions. The same
// for ticket, pull request, source, session and agent. Escape, ✕ and a click on the dimmed list close it; focus
// moves into the sheet, stays there while it is open (Tab cycles) and returns to the row that opened it.
// mode="page" renders the same content full width, without backdrop, for the "Open as page" route.

export type SidePanelProps = {
  title: string;
  // One short line under the title ("BRD-19 · demo-team/test"); no explanations.
  subtitle?: string;
  onClose: () => void;
  // "Open as page": a link to the full-page route of the same object.
  pageHref?: string;
  // Neutral actions next to "Open as page" (buttons or links rendered by the page).
  headerActions?: ReactNode;
  tabs?: Omit<SegmentedTabsProps, "size">;
  children?: ReactNode;
  // The panel's actions, primary last ("Open in Bitbucket" style); rendered right-aligned at the bottom.
  footer?: ReactNode;
  mode?: "panel" | "page";
  // "narrow" for a companion-style panel (Octryx) beside a full page; the default is the detail width.
  size?: "regular" | "narrow";
  testId?: string;
};

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Where Tab moves inside the sheet: wraps from last to first and back. -1 when focus is not trapped. */
export function trappedIndex(count: number, index: number, shift: boolean): number {
  if (!count) return -1;
  if (shift) return index <= 0 ? count - 1 : index - 1;
  return index >= count - 1 ? 0 : index + 1;
}

export function SidePanel({
  title, subtitle, onClose, pageHref, headerActions, tabs, children, footer, mode = "panel", size = "regular",
  testId = "side-panel",
}: SidePanelProps) {
  const titleId = useId();
  const sheetRef = useRef<HTMLDivElement | null>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  // Focus moves in once when the panel opens and back to the opener when it closes. Escape closes. The effect runs
  // once: callers pass a new onClose on every render (see ConfirmDialog).
  useEffect(() => {
    if (mode !== "panel" || typeof document === "undefined") return undefined;
    const opener = document.activeElement as HTMLElement | null;
    sheetRef.current?.focus?.();
    const onKey = (event: globalThis.KeyboardEvent) => {
      // Escape in a confirmation open inside the sheet closes only the confirmation (it listens after the panel).
      if (event.key === "Escape" && !event.defaultPrevented && !sheetRef.current?.querySelector?.('[role="alertdialog"]')) {
        event.preventDefault();
        closeRef.current();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
  }, [mode]);

  const onSheetKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Tab" || mode !== "panel" || !sheetRef.current?.querySelectorAll) return;
    const focusable = Array.from(sheetRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    const index = focusable.indexOf(document.activeElement as HTMLElement);
    const next = trappedIndex(focusable.length, index, event.shiftKey);
    if (next < 0) return;
    event.preventDefault();
    focusable[next].focus();
  };

  const header = createElement(
    "header",
    { className: "ds-panel__header" },
    createElement(
      "div",
      { className: "ds-panel__heading" },
      createElement("h2", { id: titleId, className: "ds-panel__title" }, title),
      subtitle ? createElement("p", { className: "ds-panel__subtitle" }, subtitle) : null,
    ),
    createElement(
      "div",
      { className: "ds-panel__header-actions" },
      headerActions,
      mode === "panel" && pageHref
        ? createElement("a", { className: "admin-panel__action-btn", href: pageHref, "data-testid": `${testId}-open-page` }, "Open as page")
        : null,
      mode === "panel"
        ? createElement("button", {
          type: "button", className: "ds-panel__close", "aria-label": `Close ${title}`, onClick: () => closeRef.current(),
          "data-testid": `${testId}-close`,
        }, "✕")
        : null,
    ),
  );

  const tabRow = tabs ? createElement("div", { className: "ds-panel__tabs" }, createElement(SegmentedTabs, { ...tabs, size: "small" })) : null;
  const panelId = tabs ? `${tabs.idPrefix ?? "ds-tabs"}-panel-${tabs.value}` : undefined;
  const body = createElement("div", {
    className: "ds-panel__body", id: panelId, role: tabs ? "tabpanel" : undefined,
    "aria-labelledby": tabs ? `${tabs.idPrefix ?? "ds-tabs"}-tab-${tabs.value}` : undefined,
  }, children);
  const foot = footer ? createElement("footer", { className: "ds-panel__footer" }, footer) : null;

  if (mode === "page") {
    return createElement("section", { className: "ds-panel ds-panel--page", "aria-labelledby": titleId, "data-testid": testId }, header, tabRow, body, foot);
  }
  return createElement(
    "div",
    { className: "ds-panel__backdrop", "data-testid": `${testId}-backdrop`, onMouseDown: (event: { target: unknown; currentTarget: unknown }) => {
      if (event.target === event.currentTarget) closeRef.current();
    } },
    createElement("div", {
      ref: sheetRef, className: `ds-panel${size === "narrow" ? " ds-panel--narrow" : ""}`, role: "dialog", "aria-modal": "true", "aria-labelledby": titleId, tabIndex: -1,
      onKeyDown: onSheetKey, "data-testid": testId,
    }, header, tabRow, body, foot),
  );
}
