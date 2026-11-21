import { useState, type ReactNode } from "react";

import { DataTable, type DataTableColumn } from "../../../layout/DataTable";
import { EmptyLine } from "../../../layout/EmptyLine";
import { SegmentedTabs } from "../../../layout/SegmentedTabs";
import { useActiveWorkspace } from "../../../chat/useActiveWorkspace";
import { ChooseWorkspaceLine } from "../../../chat/workspace/ChooseWorkspaceLine";
import { useConfirmAction } from "../confirm/useConfirmAction";
import { EmergencyStopPanel, HeldStarts, StopHistory } from "./EmergencyStop";
import { stopButtonLabel } from "./operationsEmergencyStop";
import { type ActionContext } from "./operationsActions";
import { type OperationsLive, type OpsRun } from "./operationsTypes";
import { CountBar, type Row } from "./OperationsLiveCells";
import { DevicesTable, SeatsTable } from "./OperationsLiveTables";
import { liveColumns } from "./operationsLiveColumns";
import { liveRowMenu } from "./operationsLiveMenu";
import { updatedText, useOperationsLive } from "./useOperationsLive";
import "./operations.css";

// Operations › Live: every active run with its state, where it works, its
// last sign of life and its cost; a team run opens into its items. Devices and seats below. Platform admins can widen
// it to all Workspaces; everyone else sees the active Workspace (the server falls back to the Workspace route).

type WorkspaceRef = { id: string; name: string; is_default?: boolean };
type Scope = "workspace" | "all";

export function OperationsLivePage({ projects, isAdmin = false, currentUserId = "" }: {
  projects: WorkspaceRef[]; isAdmin?: boolean; currentUserId?: string;
}) {
  const [activeId] = useActiveWorkspace(projects);
  // Starts on the active Workspace: the platform view (and its platform-wide stop) must be chosen on purpose.
  const [scope, setScope] = useState<Scope>("workspace");
  const active = projects.find((project) => project.id === activeId) ?? null;
  const all = isAdmin && (scope === "all" || !active);
  const workspaceId = all ? "" : active?.id ?? "";

  if (!all && !workspaceId) {
    return (
      <section className="ops-page" data-testid="operations-live">
        <ChooseWorkspaceLine projects={projects} purpose="to see what runs in it" />
      </section>
    );
  }
  return (
    <LiveView key={workspaceId || "all"} workspaceId={workspaceId} workspaceName={all ? "" : active?.name ?? ""}
      isAdmin={isAdmin} me={currentUserId} onShowPlatform={() => setScope("all")}
      scopeTabs={isAdmin ? (
        <SegmentedTabs label="Workspaces" size="small" idPrefix="ops-scope" testId="ops-scope"
          value={all ? "all" : "workspace"} onChange={(key) => setScope(key as Scope)}
          tabs={[...(active ? [{ key: "workspace", label: active.name }] : []), { key: "all", label: "All workspaces" }]} />
      ) : null} />
  );
}

// The scope tabs, when the data arrived, Refresh and (where allowed) the emergency stop.
function LiveToolbar({ scopeTabs, loadedAt, now, stopLabel, onRefresh, onStop }: {
  scopeTabs: ReactNode;
  loadedAt: number | null;
  now: number;
  stopLabel: string | null;
  onRefresh: () => void;
  onStop: () => void;
}) {
  return (
    <div className="ops-toolbar">
      {scopeTabs ?? <span />}
      <div className="ops-toolbar__end">
        <span className="ops-updated" data-testid="ops-updated">{updatedText(loadedAt, now)}</span>
        <button type="button" className="ds-btn" onClick={onRefresh}>Refresh</button>
        {stopLabel ? (
          <button type="button" className="ds-btn ds-btn--danger" data-testid="ops-stop" onClick={onStop}>{stopLabel}</button>
        ) : null}
      </div>
    </div>
  );
}

// Every run, followed by its items while it is expanded.
function liveRows(live: OperationsLive | null, expanded: (run: OpsRun) => boolean): Row[] {
  return (live?.runs ?? []).flatMap((run) => [
    { kind: "run" as const, run },
    ...(run.items.length && expanded(run) ? run.items.map((item) => ({ kind: "item" as const, run, item })) : []),
  ]);
}

function LiveLoadError({ scopeTabs, error, onRetry }: { scopeTabs: ReactNode; error: string; onRetry: () => void }) {
  return (
    <section className="ops-page" data-testid="operations-live">
      {scopeTabs ? <div className="ops-toolbar">{scopeTabs}</div> : null}
      <EmptyLine text={error} action={{ label: "Try again", onClick: onRetry }} testId="ops-error" />
    </section>
  );
}

function LiveRunsTable({ loading, rows, columns, menu }: {
  loading: boolean;
  rows: Row[];
  columns: DataTableColumn<Row>[];
  menu: (row: Row) => ReactNode;
}) {
  return (
    <DataTable<Row>
      label="Active runs"
      testId="ops-runs"
      loading={loading}
      loadingLabel="the live view"
      rows={rows}
      rowKey={(row) => (row.kind === "run" ? row.run.id : `${row.run.id}/${row.item.id}`)}
      empty={{ text: "No run is active right now.", testId: "ops-runs-empty" }}
      columns={columns}
      rowMenu={menu}
    />
  );
}

function LiveDevicesAndSeats({ live, elapsed }: { live: OperationsLive; elapsed: number }) {
  return (
    <div className="ops-split">
      <div className="ops-split__part">
        <h2 className="ds-section-title ops-section">Devices</h2>
        <DevicesTable devices={live.devices} live={live} elapsed={elapsed} />
      </div>
      <div className="ops-split__part">
        <h2 className="ds-section-title ops-section">Seats</h2>
        <SeatsTable seats={live.seats} />
      </div>
    </div>
  );
}

function LiveView({ workspaceId, workspaceName, isAdmin, me, scopeTabs, onShowPlatform }: {
  workspaceId: string; workspaceName: string; isAdmin: boolean; me: string; scopeTabs: ReactNode; onShowPlatform: () => void;
}) {
  const { live, error, loadedAt, now, viaWorkspace, reload } = useOperationsLive(workspaceId);
  const [stopping, setStopping] = useState(false);
  const [stops, setStops] = useState(0);
  // Emergency stop (§5): only for whoever reads this scope through the admin route; the platform for platform admins.
  const stopLabel = live ? stopButtonLabel({ all: !workspaceId, workspaceName, isPlatformAdmin: isAdmin, viaAdminRoute: !viaWorkspace }) : null;
  const confirm = useConfirmAction();
  const [notice, setNotice] = useState("");
  const [toggled, setToggled] = useState<Record<string, boolean>>({});
  const elapsed = loadedAt === null ? 0 : (now - loadedAt) / 1000;
  const ctx: ActionContext = { isAdmin, me: live?.viewerId || me, devices: live?.devices ?? [] };

  const expanded = (run: OpsRun) => toggled[run.id]
    ?? (run.state === "looping" || run.state === "problem" || run.items.some((item) => item.problems.length > 0));
  const rows = liveRows(live, expanded);
  const menu = liveRowMenu({ ctx, confirm, reload, setNotice });

  if (error && !live) {
    return <LiveLoadError scopeTabs={scopeTabs} error={error} onRetry={() => void reload()} />;
  }

  const columns = liveColumns({ live, elapsed, expanded,
    onToggle: (run) => setToggled((current) => ({ ...current, [run.id]: !expanded(run) })) });

  return (
    <section className="ops-page" data-testid="operations-live">
      <LiveToolbar scopeTabs={scopeTabs} loadedAt={loadedAt} now={now} stopLabel={stopLabel} onRefresh={() => void reload()}
        onStop={() => setStopping(true)} />
      {error ? <p className="ops-notice ops-notice--problem" role="alert">{error}</p> : null}
      {notice ? <p className="ops-notice" role="status" data-testid="ops-notice">{notice}</p> : null}
      {confirm.notice}
      {stopLabel ? (
        <HeldStarts workspaceId={workspaceId} workspaceName={workspaceId ? workspaceName : ""} reloadKey={stops}
          isPlatformAdmin={isAdmin} onShowPlatform={onShowPlatform}
          onResumed={(result) => { setNotice(result); setStops((n) => n + 1); void reload(); }} />
      ) : null}
      {live ? <CountBar live={live} /> : null}
      <h2 className="ds-section-title ops-section">Runs</h2>
      <LiveRunsTable loading={live === null} rows={rows} columns={columns} menu={menu} />
      {live ? <LiveDevicesAndSeats live={live} elapsed={elapsed} /> : null}
      {stopLabel ? <StopHistory workspaceId={workspaceId} reloadKey={stops} /> : null}
      {stopping && stopLabel ? (
        <EmergencyStopPanel label={stopLabel} workspaceId={workspaceId} onClose={() => setStopping(false)}
          onStopped={(result) => { setStopping(false); setNotice(result); setStops((n) => n + 1); void reload(); }} />
      ) : null}
      {confirm.dialog}
    </section>
  );
}
