// The props of the admin panel switch: the selected tab, its load state and each tab's context.
import type { ReadJsonFn } from "../hooks/useAdminTabLoader.types";

export type AdminPanelContentProps = {
  loadingTab: boolean;
  tabError: string | null;
  // Loads the tab again after a failed load.
  onRetry?: () => void;
  tab: string;
  projects: Array<{ id: string; name: string }>;
  readJson: ReadJsonFn;
  usersTabCtx: Record<string, unknown>;
  projectsTabCtx: Record<string, unknown>;
  providersTabCtx: Record<string, unknown>;
  runtimesTabCtx: Record<string, unknown>;
  scenariosTabCtx: Record<string, unknown>;
  connectorsTabCtx: Record<string, unknown>;
  toolCatalogTabCtx: Record<string, unknown>;
  knowledgeTabCtx: Record<string, unknown>;
  agentsTabCtx: Record<string, unknown>;
  schedulersTabCtx: Record<string, unknown>;
  tasksTabCtx: Record<string, unknown>;
  webhooksTabCtx: Record<string, unknown>;
  channelsTabCtx: Record<string, unknown>;
  mcpTabCtx: Record<string, unknown>;
  ttsTabCtx: Record<string, unknown>;
  skillsTabCtx: Record<string, unknown>;
  brandingTabCtx: Record<string, unknown>;
  // Platform feature switch from server config; the server refuses branding writes while it is off.
  brandingEnabled?: boolean;
  // Presentation only (the server authorizes every write): whether the caller is a platform admin.
  isAdmin?: boolean;
  // Who is looking (Operations › Live offers "Stop job" only on the viewer's own devices).
  currentUserId?: string;
};
