// The Workflows home: one sidebar entry opens the executable workflow list. The related
// administration pages keep their route IDs and deep links; they are listed here, in plain words,
// for the collapsed section under the list, and each of them offers the way back to Workflows.
import { listAdminChildPages } from "../../config/adminPanelAreas";
import type { AdminTab } from "../../types/adminPanelTypes.governance";

export const WORKFLOWS_HOME_TAB: AdminTab = "workflowList";

export const WORKFLOWS_HOME = { tab: WORKFLOWS_HOME_TAB, label: "Workflows" } as const;

export type WorkflowAdministrationPage = { tab: AdminTab; title: string; purpose: string };

// What each page is for, from the user's point of view.
const PURPOSE: Partial<Record<AdminTab, string>> = {
  scenarios: "How much context the agent gets for a recurring kind of request. A scenario never chooses a workflow.",
};

// The designer (D2b1) is the Workflows page with one workflow open, not an administration page either.
const PAGE_TABS = new Set<string>(["workflowChecks", "workflowDesigner"]);

export function workflowAdministrationPages(): WorkflowAdministrationPage[] {
  // Check results is a tab of the Workflows page itself, not an administration page.
  return listAdminChildPages("workflows", WORKFLOWS_HOME_TAB).filter((ref) => !PAGE_TABS.has(ref.id)).map((ref) => ({
    tab: ref.id,
    title: ref.label ?? ref.id,
    purpose: PURPOSE[ref.id] ?? "",
  }));
}
