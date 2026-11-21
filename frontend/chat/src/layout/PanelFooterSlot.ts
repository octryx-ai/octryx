import { createContext, createElement, Fragment, useContext, type ReactNode } from "react";
import { createPortal } from "react-dom";

// A side panel's footer as a slot: a form deep inside a panel (the provider's gateway settings)
// puts its Save into the panel footer, bottom right, instead of the end of the scrolled content. The panel owner
// renders <div ref={setSlot} className="ds-panel__footer-slot" /> as the SidePanel footer and provides the element;
// without a slot (tests, a page without a panel) the actions render in place.

export const PanelFooterSlotContext = createContext<HTMLElement | null>(null);

export function PanelFooterActions({ children }: { children?: ReactNode }) {
  const slot = useContext(PanelFooterSlotContext);
  return slot ? createPortal(children, slot) : createElement(Fragment, null, children);
}
