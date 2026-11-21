import { createElement } from "react";

// The one empty state (design system): one line and at most one action, no box, no illustration.

export type EmptyLineProps = {
  // One sentence: what is missing ("No pull requests yet.").
  text: string;
  // The one next step; a link (href) or a button (onClick).
  action?: { label: string; href?: string; onClick?: () => void };
  testId?: string;
};

export function EmptyLine({ text, action, testId = "empty-line" }: EmptyLineProps) {
  const actionNode = !action
    ? null
    : action.href
      ? createElement("a", { className: "ds-empty__action", href: action.href, onClick: action.onClick }, action.label)
      : createElement("button", { type: "button", className: "ds-empty__action ds-link-button", onClick: action.onClick }, action.label);
  return createElement("p", { className: "ds-empty", role: "status", "data-testid": testId }, createElement("span", null, text), actionNode);
}
