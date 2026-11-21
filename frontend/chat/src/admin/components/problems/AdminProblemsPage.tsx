import { useState } from "react";

import { SegmentedTabs } from "../../../layout/SegmentedTabs";
import { useActiveWorkspace } from "../../../chat/useActiveWorkspace";
import { ChooseWorkspaceLine } from "../../../chat/workspace/ChooseWorkspaceLine";
import { ProblemsView } from "./ProblemsView";
import "./problems.css";

// Admin › Problems: the problems of the active Workspace, the one the global switch sets (no
// own Workspace dropdown). Platform admins can widen it to "All workspaces" (the admin endpoint without a filter);
// without an active Workspace they see all, everyone else is asked to choose one. The purpose sentence comes from
// pagePurpose.ts via the admin shell. `workspace_id` in the address is the active Workspace (useActiveWorkspace) and
// `kind` sets the kind filter on load, so "Open in Problems" from a Workspace lands filtered.

type WorkspaceRef = { id: string; name: string; is_default?: boolean };
type Scope = "workspace" | "all";

function addressKind(): string {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get("kind") ?? "";
}

export function AdminProblemsPage({ projects, isAdmin = false }: { projects: WorkspaceRef[]; isAdmin?: boolean }) {
  const [initialKind] = useState(addressKind);
  const [activeId] = useActiveWorkspace(projects);
  const [scope, setScope] = useState<Scope>("workspace");
  const active = projects.find((project) => project.id === activeId) ?? null;
  const all = isAdmin && (scope === "all" || !active);
  const workspaceId = all ? "" : active?.id ?? "";

  if (!all && !workspaceId) {
    return (
      <section className="problems-page" data-testid="admin-problems">
        <ChooseWorkspaceLine projects={projects} purpose="to see its problems" />
      </section>
    );
  }
  return (
    <section className="problems-page" data-testid="admin-problems">
      {isAdmin ? (
        <div className="problems__scope">
          <SegmentedTabs label="Workspaces" size="small" idPrefix="problems-scope" testId="problems-scope"
            value={all ? "all" : "workspace"} onChange={(key) => setScope(key as Scope)}
            tabs={[...(active ? [{ key: "workspace", label: active.name }] : []), { key: "all", label: "All workspaces" }]} />
        </div>
      ) : null}
      <ProblemsView key={workspaceId || "all"} scope={{ kind: "admin", workspaceId: workspaceId || undefined }}
        showWorkspace={!workspaceId} initialKind={initialKind} />
    </section>
  );
}
