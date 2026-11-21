import { useCallback, useEffect, useState } from "react";

import { DataTable, type DataTableColumn } from "../../../layout/DataTable";
import { EmptyLine } from "../../../layout/EmptyLine";
import { SegmentedTabs } from "../../../layout/SegmentedTabs";
import { StatusLabel } from "../../../layout/StatusLabel";
import { TimeText } from "../../utils/TimeText";
import { ActionMenu } from "../workflowSurfaces/ActionMenu";
import { acknowledgeProblem, isRefusal, loadAdminProblems, loadWorkspaceProblems } from "./problemsApi";
import {
  countText,
  kindTabs,
  severityLabel,
  severityTabs,
  type Problem,
  type ProblemList,
  type ProblemRef,
} from "./problemsModel";

// E5 Problems: one table of what is broken, each row linking the one place to fix it. The admin scope covers the
// platform (or one Workspace through the filter) and can hide a problem until it happens again; the Workspace
// scope is what a Workspace's members see (the future Workspace page reuses it).

export type ProblemsScope = { kind: "admin"; workspaceId?: string } | { kind: "workspace"; workspaceId: string };

type Loaded = { kind: "ok"; list: ProblemList } | { kind: "error"; message: string } | null;

export function ProblemsView({ scope, showWorkspace = true, initialKind = "" }: {
  scope: ProblemsScope; showWorkspace?: boolean; initialKind?: string;
}) {
  const [kind, setKind] = useState(initialKind);
  const [severity, setSeverity] = useState("");
  const [loaded, setLoaded] = useState<Loaded>(null);
  const [notice, setNotice] = useState("");
  const workspaceId = scope.workspaceId ?? "";

  const load = useCallback(async () => {
    setLoaded(await fetchProblems(scope.kind, workspaceId, kind, severity));
  }, [scope.kind, workspaceId, kind, severity]);

  useEffect(() => {
    void load();
  }, [load]);

  const hide = async (problem: Problem) => {
    try {
      await acknowledgeProblem(problem.key);
      setNotice(`Hidden until it happens again: ${problem.title}`);
    } catch (error) {
      setNotice(isRefusal(error) ? error.message : "The problem could not be hidden.");
    }
    await load();
  };

  if (loaded?.kind === "error") {
    return <EmptyLine text={loaded.message} action={{ label: "Try again", onClick: () => void load() }} testId="problems-error" />;
  }
  const list = loaded?.kind === "ok" ? loaded.list : null;
  // Workspace members get no severity filter on the server; keep the rows to the chosen severity here.
  const rows = (list?.problems ?? []).filter((problem) => scope.kind === "admin" || !severity || problem.severity === severity);
  const filtered = Boolean(kind || severity);

  return (
    <div className="problems" data-testid="problems-view">
      {notice ? <p className="problems__notice" role="status" data-testid="problems-notice">{notice}</p> : null}
      {list ? <ProblemFilters list={list} kind={kind} setKind={setKind} severity={severity} setSeverity={setSeverity} /> : null}
      <DataTable<Problem>
        label="Problems"
        testId="problems-table"
        loading={list === null}
        rows={rows}
        rowKey={(problem) => problem.key}
        empty={filtered
          ? { text: "No problem matches this filter.", testId: "problems-empty",
            action: { label: "Show all", onClick: () => { setKind(""); setSeverity(""); } } }
          : { text: "No problems.", testId: "problems-empty" }}
        columns={problemColumns(showWorkspace)}
        rowMenu={scope.kind === "admin" ? (problem) => (
          <ActionMenu row={{ objectName: problem.title }}
            items={[{ label: "Hide until it happens again", onSelect: () => void hide(problem) }]} />
        ) : undefined}
      />
    </div>
  );
}

// Loads one page of problems for the scope; a refusal reads as one sentence.
async function fetchProblems(scopeKind: ProblemsScope["kind"], workspaceId: string, kind: string, severity: string): Promise<Loaded> {
  try {
    const list = scopeKind === "admin"
      ? await loadAdminProblems({ workspaceId, kind, severity })
      : await loadWorkspaceProblems(workspaceId, kind);
    return { kind: "ok", list };
  } catch (error) {
    return { kind: "error", message: isRefusal(error) ? error.message : "The problems could not be loaded." };
  }
}

// The kind and severity filters, each with the server's totals.
function ProblemFilters({ list, kind, setKind, severity, setSeverity }: {
  list: ProblemList; kind: string; setKind: (kind: string) => void; severity: string; setSeverity: (severity: string) => void;
}) {
  return (
    <div className="problems__filters">
      <SegmentedTabs label="Kind" size="small" idPrefix="problems-kind" value={kind} testId="problems-kind"
        tabs={kindTabs(list.counts)} onChange={setKind} />
      <SegmentedTabs label="Severity" size="small" idPrefix="problems-severity" value={severity} testId="problems-severity"
        tabs={severityTabs(list.counts)} onChange={setSeverity} />
    </div>
  );
}

// The table's columns; the Workspace column only where problems of several Workspaces are listed.
function problemColumns(showWorkspace: boolean): DataTableColumn<Problem>[] {
  return [
    { key: "severity", header: "Severity", nowrap: true, render: (problem) => {
      const state = severityLabel(problem.severity);
      return <StatusLabel label={state.label} tone={state.tone} />;
    } },
    { key: "what", header: "What", grow: true, render: (problem) => problem.title },
    ...(showWorkspace ? [{ key: "workspace", header: "Workspace", nowrap: true,
      render: (problem: Problem) => workspaceText(problem.workspace) }] : []),
    { key: "since", header: "Since", nowrap: true, render: (problem) => <TimeText value={problem.since} mode="recent" /> },
    { key: "count", header: "Count", nowrap: true, align: "end", render: (problem) => countText(problem.count) },
    { key: "fix", header: "Fix", nowrap: true, render: (problem) => (problem.fix
      ? <a className="ds-link-button" href={problem.fix.href} data-testid="problems-fix">{problem.fix.label}</a>
      : "—") },
  ];
}

function workspaceText(workspace: ProblemRef | null): string {
  return workspace ? workspace.name : "Platform";
}

/** What a Workspace's members see; ready for the Workspace page. */
export function WorkspaceProblems({ workspaceId }: { workspaceId: string }) {
  return <ProblemsView scope={{ kind: "workspace", workspaceId }} showWorkspace={false} />;
}
