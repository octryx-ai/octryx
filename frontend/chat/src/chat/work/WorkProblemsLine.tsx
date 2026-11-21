import { useEffect, useState } from "react";

import { SidePanel } from "../../layout/SidePanel";
import { loadWorkspaceProblems } from "../../admin/components/problems/problemsApi";
import { WorkspaceProblems } from "../../admin/components/problems/ProblemsView";
import type { ProblemList } from "../../admin/components/problems/problemsModel";
import { workProblemsLine } from "./workProblemsModel";
import { knowledgeDocumentsHref } from "../chatOnboarding";

// One quiet line in the Work header when the active Workspace has problems; "Show" lists them in the side panel.
// Unavailable (404, not a member) or none: nothing is shown.
export function WorkProblemsLine({ workspaceId, reloadKey }: { workspaceId: string; reloadKey?: number }) {
  const [list, setList] = useState<ProblemList | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let current = true;
    setList(null);
    if (!workspaceId) return () => { current = false; };
    (async () => {
      try {
        const next = await loadWorkspaceProblems(workspaceId);
        if (current) setList(next);
      } catch {
        if (current) setList(null);
      }
    })();
    return () => { current = false; };
  }, [workspaceId, reloadKey]);

  const line = workProblemsLine(list);
  if (!line) return null;
  return (
    <>
      <p className={`work-problems-line work-problems-line--${line.tone}`} data-testid="work-problems-line">
        <span>{line.text}</span>
        <span aria-hidden="true"> · </span>
        {line.target === "knowledge" ? (
          <a className="work-problems-line__show" href={knowledgeDocumentsHref(workspaceId)} data-testid="work-problems-knowledge">
            Open Knowledge
          </a>
        ) : (
          <button type="button" className="work-problems-line__show" onClick={() => setOpen(true)}>Show</button>
        )}
      </p>
      {open ? (
        <SidePanel title="Problems in this Workspace" onClose={() => setOpen(false)} testId="work-problems">
          <WorkspaceProblems workspaceId={workspaceId} />
        </SidePanel>
      ) : null}
    </>
  );
}
