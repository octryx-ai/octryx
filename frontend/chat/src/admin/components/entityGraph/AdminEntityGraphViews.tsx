import type { ComponentProps } from "react";
import type { ProjectOptionRow } from "../knowledgeTypes";
import { AdminEntityGraphPanel } from "./AdminEntityGraphPanel";

type Props = Omit<ComponentProps<typeof AdminEntityGraphPanel>, "projectId"> & {
  projectId: string;
  setProjectId: (value: string) => void;
  projects: ProjectOptionRow[];
};

export function AdminEntityGraphViews({ projectId, setProjectId: _setProjectId, projects: _projects, ...shared }: Props) {
  // Keyed by workspace so a previous search or selection never filters another workspace.
  return <AdminEntityGraphPanel key={projectId} projectId={projectId} {...shared} />;
}
