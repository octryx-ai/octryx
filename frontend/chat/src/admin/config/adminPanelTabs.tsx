import type { ReactNode } from "react";
import type { AdminTab } from "../types/adminPanelTypes.governance";
import { OBSERVABILITY_TAB_GROUP } from "./observabilityTabs";
import { KNOWLEDGE_ADMIN_TAB_GROUP } from "./knowledgeAdminTabs";
import { IDENTITY_TAB_GROUP } from "./identityAdminTabs";
import { ORGANIZATION_TAB_GROUP } from "./organizationAdminTabs";
import { POLICY_TAB_GROUP } from "./policyAdminTabs";
import { INFRASTRUCTURE_TAB_GROUP } from "./infrastructureAdminTabs";
import { AUTOMATION_TAB_GROUP } from "./automationAdminTabs";
import { CHANNELS_AI_TAB_GROUP } from "./channelsAiAdminTabs";
import { AREA_PAGES_TAB_GROUP } from "./areaPagesAdminTabs";
import { CENTRAL_CONFIG_TAB_GROUP } from "./centralConfigAdminTabs";

export type AdminTabDef = {
  id: AdminTab;
  label: string;
  icon: ReactNode;
  children?: AdminTabDef[];
};

export type AdminTabGroup = {
  label: string;
  tabs: AdminTabDef[];
};

export const ADMIN_TAB_GROUPS: AdminTabGroup[] = [
  IDENTITY_TAB_GROUP,
  ORGANIZATION_TAB_GROUP,
  POLICY_TAB_GROUP,
  INFRASTRUCTURE_TAB_GROUP,
  AUTOMATION_TAB_GROUP,
  CHANNELS_AI_TAB_GROUP,
  AREA_PAGES_TAB_GROUP,
  CENTRAL_CONFIG_TAB_GROUP,
  OBSERVABILITY_TAB_GROUP,
  KNOWLEDGE_ADMIN_TAB_GROUP,
];

export function resolveAdminTabLabel(tab: AdminTab): string {
  return (
    ADMIN_TAB_GROUPS.flatMap((group) =>
      group.tabs.flatMap((entry) => [entry, ...(entry.children ?? [])]),
    ).find((entry) => entry.id === tab)?.label ?? ""
  );
}
