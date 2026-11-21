// A workflow that runs as a flow, opened in the Canvas: the flow builder's editor (validate,
// run, publish, run & results, drafts), embedded. It opens the flow named by `flow_id` in the address (its deep
// link), so it is mounted once per flow; "← All workflows" returns to the Workflows list.
import { lazy, Suspense } from "react";

import type { ReadJsonFn } from "../../../hooks/useAdminTabLoader.types";
import type { ProjectOption } from "../../../../chatOptionTypes";

const AdminFlowBuilderTab = lazy(async () => {
  const module = await import("../../flowBuilder/AdminFlowBuilderTab");
  return { default: module.AdminFlowBuilderTab };
});

type FlowWorkflowEditorProps = {
  projects: ProjectOption[];
  readJson: ReadJsonFn;
  onExit: () => void;
  onDirtyChange: (dirty: boolean) => void;
};

export function FlowWorkflowEditor({ projects, readJson, onExit, onDirtyChange }: FlowWorkflowEditorProps) {
  return (
    <Suspense fallback={<p className="admin-panel__hint" role="status">Loading the canvas…</p>}>
      <AdminFlowBuilderTab projects={projects} readJson={readJson} onExit={onExit} onDirtyChange={onDirtyChange} />
    </Suspense>
  );
}
