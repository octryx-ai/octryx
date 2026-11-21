import { useId } from "react";
import type { ProjectOption } from "./flowBuilderDefaults";

type FlowRunWorkspaceFieldProps = {
  flowProjectId: string | null | undefined;
  runProjectId: string;
  options: ProjectOption[];
  onChange: (projectId: string) => void;
};

// A DAG run starts in a Workspace: a Workspace's flow in its own, a platform flow in the one chosen here
// (runs and test cases are refused without one).
export function FlowRunWorkspaceField({ flowProjectId, runProjectId, options, onChange }: FlowRunWorkspaceFieldProps) {
  const id = useId();
  if (flowProjectId) {
    const name = options.find((option) => option.id === flowProjectId)?.name ?? flowProjectId;
    return <p className="admin-panel__hint">Runs in the Workspace {name}.</p>;
  }
  return (
    <label className="admin-panel__field flow-run-panel__field" htmlFor={id}>
      <span>Run in Workspace</span>
      <select id={id} value={runProjectId} onChange={(event) => onChange(event.target.value)}>
        <option value="">Choose a Workspace</option>
        {options.map((option) => <option key={option.id} value={option.id}>{option.name}</option>)}
      </select>
    </label>
  );
}
