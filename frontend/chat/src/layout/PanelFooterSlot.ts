import { createContext, createElement, Fragment, useContext, type ReactNode } from "react";
import { createPortal } from "react-dom";

// Without a slot (tests, a page without a panel) the actions render in place.

export const PanelFooterSlotContext = createContext<HTMLElement | null>(null);

export function PanelFooterActions({ children }: { children?: ReactNode }) {
  const slot = useContext(PanelFooterSlotContext);
  return slot ? createPortal(children, slot) : createElement(Fragment, null, children);
}
