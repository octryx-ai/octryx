// Knowledge → Explore → Graph: the relationships graph only. Source search lives in Knowledge → Search, so there
// is no second search surface here. The workspace comes from the page's shared workspace selector;
// `setProjectId` and `projects` stay in the props for callers that still pass them. Explore hands its shared
// filter, selection and "Search for this" through.

import type { ComponentProps } from "react";
import type { ProjectOptionRow } from "../knowledgeTypes";
import { AdminEntityGraphPanel } from "./AdminEntityGraphPanel";

type Props = Omit<ComponentProps<typeof AdminEntityGraphPanel>, "projectId"> & {
  projectId: string;
  setProjectId: (value: string) => void;
  projects: ProjectOptionRow[];
};

export function AdminEntityGraphViews({ projectId, setProjectId: _setProjectId, projects: _projects, ...shared }: Props) {
  // Keyed by workspace so a previous search or selection can never filter another workspace.
  return <AdminEntityGraphPanel key={projectId} projectId={projectId} {...shared} />;
}
