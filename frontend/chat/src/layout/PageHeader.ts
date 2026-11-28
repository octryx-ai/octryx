import { createElement, type ReactNode, type Ref } from "react";

import { openPageHelp } from "../help/usePageHelp";

// Plain .ts with createElement (no JSX, no CSS import) so every page and its unit-test loader can require it.

export type PageHeaderProps = {
  eyebrow: string;
  title: string;
  purpose?: string | null;
  workspace?: ReactNode;
  secondary?: ReactNode;
  primary?: ReactNode;
  // Admin pages portal their own controls into this container (AdminHeaderActions).
  actionsRef?: Ref<HTMLDivElement>;
  trailing?: ReactNode;
  testIds?: { eyebrow?: string; purpose?: string };
};

const HELP_ICON = [
  createElement("circle", { key: "c", cx: 12, cy: 12, r: 9 }),
  createElement("path", { key: "q", d: "M9.7 9a2.4 2.4 0 0 1 4.6.9c0 1.7-2.3 2.1-2.3 3.6" }),
  createElement("path", { key: "d", d: "M12 17h.01" }),
];

export function PageHelpButton() {
  return createElement(
    "button",
    { type: "button", className: "page-help-button", onClick: openPageHelp, "aria-label": "Help for this page", title: "Help for this page" },
    createElement("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" }, ...HELP_ICON),
  );
}

export function openedFromSetup(search: string | undefined = globalThis.location?.search): boolean {
  try {
    return new URLSearchParams(search ?? "").get("from") === "setup";
  } catch {
    return false;
  }
}

export function PageHeader({ eyebrow, title, purpose, workspace, secondary, primary, actionsRef, trailing, testIds }: PageHeaderProps) {
  return createElement(
    "header",
    { className: "page-header", "data-testid": "page-header" },
    createElement(
      "div",
      { className: "page-header__copy" },
      openedFromSetup()
        ? createElement("a", { className: "page-header__back", href: "/chat?area=help&tab=setup", "data-testid": "back-to-setup" },
          "← Back to setup guide")
        : null,
      createElement("div", { className: "page-header__eyebrow", "data-testid": testIds?.eyebrow }, eyebrow),
      createElement("h1", { className: "page-header__title" }, title),
      purpose ? createElement("p", { className: "page-header__purpose", "data-testid": testIds?.purpose }, purpose) : null,
    ),
    createElement(
      "div",
      { className: "page-header__actions", ref: actionsRef },
      workspace ?? null,
      secondary ?? null,
      primary ?? null,
    ),
    createElement(PageHelpButton),
    trailing ?? null,
  );
}
