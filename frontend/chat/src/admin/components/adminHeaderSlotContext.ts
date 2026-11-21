import { createContext } from "react";

// The right side of the admin page header (AdminPanelShell), where a page renders its compact header controls.
export const AdminHeaderSlotContext = createContext<HTMLElement | null>(null);
