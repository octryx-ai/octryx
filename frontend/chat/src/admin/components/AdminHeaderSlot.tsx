import { useContext, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { AdminHeaderSlotContext } from "./adminHeaderSlotContext";

// A page's compact header controls (e.g. the policy engine status card), rendered into the admin page header.
// Without a shell (tests, embedded use) they render in place.
export function AdminHeaderActions({ children }: { children: ReactNode }) {
  const slot = useContext(AdminHeaderSlotContext);
  return slot ? createPortal(children, slot) : <>{children}</>;
}
