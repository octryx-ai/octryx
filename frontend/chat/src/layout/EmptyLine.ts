import { createElement } from "react";

export type EmptyLineProps = {
  text: string;
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
