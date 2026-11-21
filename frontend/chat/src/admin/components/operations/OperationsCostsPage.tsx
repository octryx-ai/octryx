import { useCallback, useEffect, useState } from "react";

import { DataTable, type DataTableColumn } from "../../../layout/DataTable";
import { EmptyLine } from "../../../layout/EmptyLine";
import { SegmentedTabs } from "../../../layout/SegmentedTabs";
import { useActiveWorkspace } from "../../../chat/useActiveWorkspace";
import { ChooseWorkspaceLine } from "../../../chat/workspace/ChooseWorkspaceLine";
import { SeatCell } from "../../../chat/cost/SeatCell";
import { seatHeading } from "../../../chat/cost/seatEquivalent";
import { loadCosts, loadRunSession } from "./operationsApi";
import {
  costCell,
  deliveredText,
  GROUP_TABS,
  PERIOD_TABS,
  perDeliveredText,
  periodText,
  rowLink,
  type CostGroup,
  type CostReport,
  type CostRow,
} from "./costsModel";
import { openHref } from "./operationsActions";
import { SeatUsageView } from "./SeatUsageView";
import { useSeatUsage } from "./useSeatUsage";
import "./operations.css";

// Operations › Costs: what the runs of a period cost and what they delivered, per
// workflow, work item, run, person or Workspace; one table sorted by cost with a total row. Platform admins can widen
// it to all Workspaces, like Live; the server refuses everyone outside the Problems scope (shown verbatim).
// Two views: "API cost" (the report; the seat's API equivalent in its own column, never summed
// in) and "Seats by person" (what each person's seat calls would cost via the API at list price). The second is hidden
// while the server has no seat-usage route.

type WorkspaceRef = { id: string; name: string; is_default?: boolean };
type Scope = "workspace" | "all";
type Row = CostRow & { total?: boolean };
type View = "api" | "seats";
const VIEW_TABS = [{ key: "api", label: "API cost" }, { key: "seats", label: "Seats by person" }];

export function OperationsCostsPage({ projects, isAdmin = false }: { projects: WorkspaceRef[]; isAdmin?: boolean }) {
  const [activeId] = useActiveWorkspace(projects);
  const [scope, setScope] = useState<Scope>("all");
  const [days, setDays] = useState(30);
  const [group, setGroup] = useState<CostGroup>("workflow");
  const [view, setView] = useState<View>("api");
  const [report, setReport] = useState<CostReport | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const active = projects.find((project) => project.id === activeId) ?? null;
  const all = isAdmin && (scope === "all" || !active);
  const workspaceId = all ? "" : active?.id ?? "";

  const load = useCallback(async () => {
    if (!all && !workspaceId) return;
    setReport(null);
    setError("");
    try {
      setReport(await loadCosts({ workspaceId, days, group }));
    } catch (failure) {
      setError(failure instanceof Error && failure.message ? failure.message : "The costs could not be loaded.");
    }
  }, [all, workspaceId, days, group]);

  useEffect(() => { void load(); }, [load]);
  const seats = useSeatUsage({ workspaceId, days, ready: all || Boolean(workspaceId) });
  const shown: View = seats.missing ? "api" : view;

  const openRun = (runId: string, label: string) => openRunChat(runId, label, workspaceId, setNotice);

  if (!all && !workspaceId) {
    return (
      <section className="ops-page" data-testid="operations-costs">
        <ChooseWorkspaceLine projects={projects} purpose="to see its costs" />
      </section>
    );
  }

  return (
    <section className="ops-page" data-testid="operations-costs">
      {seats.missing ? null : (
        <div className="ops-view-switch">
          <SegmentedTabs label="Cost view" idPrefix="costs-view" testId="costs-view"
            value={shown} onChange={(key) => setView(key as View)} tabs={VIEW_TABS} />
        </div>
      )}
      <CostsToolbar isAdmin={isAdmin} active={active} all={all} days={days} group={group} shown={shown}
        onScope={setScope} onDays={setDays} onGroup={setGroup} />
      {notice ? <p className="ops-notice" role="status">{notice}</p> : null}
      {shown === "seats" ? <SeatUsageView state={seats} /> : error ? (
        <EmptyLine text={error} action={{ label: "Try again", onClick: () => void load() }} testId="costs-error" />
      ) : (
        <CostsTable report={report} days={days} group={group} workspaceId={workspaceId} onOpenRun={openRun} />
      )}
      {shown === "api" && report && !error ? <p className="ops-muted" data-testid="costs-period-text">{periodText(report)}</p> : null}
    </section>
  );
}

// Opens the run's main chat, or says why it cannot.
async function openRunChat(runId: string, label: string, workspaceId: string, setNotice: (notice: string) => void) {
  setNotice("");
  try {
    const session = await loadRunSession(runId);
    if (session) window.location.assign(openHref(session, workspaceId || undefined));
    else setNotice(`“${label}” has no chat to open.`);
  } catch (failure) {
    setNotice(failure instanceof Error && failure.message ? failure.message : "The run could not be opened.");
  }
}

// One table sorted by cost, with a total row when there are rows.
function CostsTable({ report, days, group, workspaceId, onOpenRun }: {
  report: CostReport | null;
  days: number;
  group: CostGroup;
  workspaceId: string;
  onOpenRun: (runId: string, label: string) => Promise<void>;
}) {
  const rows: Row[] = report ? [...report.rows, ...(report.rows.length ? [{ ...report.totals, total: true }] : [])] : [];
  const groupLabel = GROUP_TABS.find((tab) => tab.key === group)?.label ?? "Group";
  return (
    <DataTable<Row>
      label="Costs"
      testId="costs-table"
      loading={report === null}
      loadingLabel="the costs"
      rows={rows}
      rowKey={(row) => (row.total ? "__total" : row.key || `none-${row.label}`)}
      empty={{ text: `No run started in the last ${days} days.`, testId: "costs-empty" }}
      columns={costColumns(groupLabel, (row) => <CostLabel row={row} group={group} workspaceId={workspaceId} onOpenRun={onOpenRun} />)}
    />
  );
}

function CostsToolbar({ isAdmin, active, all, days, group, shown, onScope, onDays, onGroup }: {
  isAdmin: boolean;
  active: WorkspaceRef | null;
  all: boolean;
  days: number;
  group: CostGroup;
  shown: View;
  onScope: (scope: Scope) => void;
  onDays: (days: number) => void;
  onGroup: (group: CostGroup) => void;
}) {
  return (
    <div className="ops-toolbar">
      <div className="ops-toolbar__start">
        {isAdmin ? (
          <SegmentedTabs label="Workspaces" size="small" idPrefix="costs-scope" testId="costs-scope"
            value={all ? "all" : "workspace"} onChange={(key) => onScope(key as Scope)}
            tabs={[...(active ? [{ key: "workspace", label: active.name }] : []), { key: "all", label: "All workspaces" }]} />
        ) : null}
        <SegmentedTabs label="Period" size="small" idPrefix="costs-period" testId="costs-period"
          value={String(days)} onChange={(key) => onDays(Number(key))} tabs={PERIOD_TABS} />
      </div>
      {shown === "api" ? (
        <SegmentedTabs label="Group by" size="small" idPrefix="costs-group" testId="costs-group"
          value={group} onChange={(key) => onGroup(key as CostGroup)} tabs={GROUP_TABS} />
      ) : null}
    </div>
  );
}

// The first cell: the total, a link to the work item, a button that opens the run's chat, or the plain label.
function CostLabel({ row, group, workspaceId, onOpenRun }: {
  row: Row;
  group: CostGroup;
  workspaceId: string;
  onOpenRun: (runId: string, label: string) => Promise<void>;
}) {
  if (row.total) return <span className="ops-strong">Total</span>;
  const link = rowLink(group, row, workspaceId);
  if (link?.kind === "href") return <a className="ds-link-button" href={link.href} title={row.label}>{row.label}</a>;
  if (link?.kind === "run") {
    return <button type="button" className="ds-link-button" title={`Open ${row.label}`}
      onClick={() => void onOpenRun(link.runId, row.label)}>{row.label}</button>;
  }
  return <span title={row.label}>{row.label}</span>;
}

function costColumns(groupLabel: string, label: (row: Row) => JSX.Element): DataTableColumn<Row>[] {
  return [
    { key: "label", header: groupLabel, grow: true, clip: "28rem", render: label },
    { key: "cost", header: "API cost", nowrap: true, align: "end", render: (row) => <Strong total={row.total}>{costCell(row.costUsd)}</Strong> },
    { key: "seat", header: seatHeading(), nowrap: true, align: "end", render: (row) => <SeatCell figures={row.seat} strong={row.total} /> },
    { key: "runs", header: "Runs", nowrap: true, align: "end", render: (row) => <Strong total={row.total}>{String(row.runs)}</Strong> },
    { key: "delivered", header: "Delivered", nowrap: true, align: "end", render: (row) => <Strong total={row.total}>{deliveredText(row)}</Strong> },
    { key: "prs", header: "Pull requests", nowrap: true, align: "end", render: (row) => <Strong total={row.total}>{String(row.pullRequests)}</Strong> },
    { key: "per", header: "API cost per delivered run", nowrap: true, align: "end", render: (row) => {
      const value = perDeliveredText(row);
      return <Strong total={row.total} muted={value === "—"}>{value}</Strong>;
    } },
  ];
}

function Strong({ total, muted, children }: { total?: boolean; muted?: boolean; children: string }) {
  return <span className={`${total ? "ops-strong" : ""}${muted ? " ops-muted" : ""}`.trim() || undefined}>{children}</span>;
}
