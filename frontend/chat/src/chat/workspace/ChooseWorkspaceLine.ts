import { createElement, useId } from "react";
import { useActiveWorkspace } from "../useActiveWorkspace";

type WorkspaceOption = { id: string; name: string; isDefault?: boolean; is_default?: boolean };

// The page's own Workspace choice while none is active (fresh-install review): one line "Choose a workspace:
// [select]" that sets the one global context, so no page depends on the rail icon alone. Without Workspaces it
// says whom to ask. Plain createElement (no JSX, no CSS import) so the unit-test loaders can load it.
export function ChooseWorkspaceLine({ projects, purpose, testId = "choose-workspace" }: {
  projects: WorkspaceOption[];
  purpose?: string;
  testId?: string;
}) {
  const [, setWorkspaceId] = useActiveWorkspace(projects);
  const selectId = useId();
  if (!projects.length) {
    return createElement("p", { className: "admin-panel__empty-state choose-workspace", "data-testid": testId },
      "No workspaces available. Ask your workspace administrator for access to the workspace you need.");
  }
  return createElement("div", { className: "admin-panel__empty-state choose-workspace", "data-testid": testId },
    createElement("label", { htmlFor: selectId }, `Choose a workspace${purpose ? ` ${purpose}` : ""}:`),
    createElement("select", {
      id: selectId, className: "admin-panel__input choose-workspace__select", defaultValue: "",
      "data-testid": `${testId}-select`,
      onChange: (event: { target: { value: string } }) => { if (event.target.value) setWorkspaceId(event.target.value); },
    },
    createElement("option", { value: "", disabled: true }, "Select…"),
    ...projects.map((project) => createElement("option", { key: project.id, value: project.id }, project.name))));
}
