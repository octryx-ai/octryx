import { useEffect, useState } from "react";

import { ConnectorBrandIcon } from "../../../admin/components/ConnectorBrandIcon";
import { loadIntakeOverview } from "./workIntakeApi";
import {
  automationLabel,
  connectionLabel,
  gapSource,
  knowledgeLabel,
  scheduleLabel,
  sourceLabel,
  whatLabel,
  workLabel,
  workSourcesSummary,
} from "./workIntakeModel";
import type { IntakeOverview, IntakeSource, IntakeSummary } from "./workIntakeTypes";
import { WorkIntakeRunHistory } from "./WorkIntakeRunHistory";
import { WorkIntakeSetupDrawer, type IntakeSetupTarget } from "./WorkIntakeSetupDrawer";
import { cardSyncLabel, workflowModeOf } from "./intakeSyncModel";
import { previewIntake } from "./workIntakeSetupApi";
import "./workIntake.css";
import { LoadingState } from "../../../layout/LoadingState";

type WorkIntakeActions = {
  onOpenConnectors: () => void;
  onSetUp: (sourceKind: string) => void;
  onEdit: (intake: IntakeSummary) => void;
  onPreview: (intake: IntakeSummary) => void;
};

// Work → Configure → Intake: which items flow from this Workspace's
// connections into Work. Connections are declared in Workspace → Connectors; an intake only picks from them.
export function WorkIntakePage({ workspaceId, workspaceName, reloadKey, onOpenConnectors }: {
  workspaceId: string;
  workspaceName: string;
  reloadKey?: string | number;
  onOpenConnectors: () => void;
}) {
  const [overview, setOverview] = useState<IntakeOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [setup, setSetup] = useState<IntakeSetupTarget | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [localReload, setLocalReload] = useState(0);
  const reload = `${reloadKey ?? ""}:${localReload}`;
  const actions: WorkIntakeActions = {
    onOpenConnectors,
    onSetUp: (sourceKind) => { setNotice(null); setSetup({ sourceKind }); },
    onEdit: (intake) => { setNotice(null); setSetup({ intakeId: intake.id }); },
    onPreview: (intake) => {
      setNotice(null);
      previewIntake(workspaceId, intake.id)
        .then(() => setNotice(`Preview of "${intake.name}" finished; nothing was written. See its run history.`))
        .catch((failure) => setNotice(failure instanceof Error ? failure.message : "The preview failed."))
        .finally(() => setLocalReload((value) => value + 1));
    },
  };

  useEffect(() => {
    let active = true;
    setOverview(null);
    setError(null);
    loadIntakeOverview(workspaceId)
      .then((next) => active && setOverview(next))
      .catch((err) => active && setError(err instanceof Error ? err.message : "Could not load the intake overview."));
    return () => {
      active = false;
    };
  }, [workspaceId, reload]);

  if (error) return <div className="work-area__error">{error}</div>;
  if (!overview) return <LoadingState label="intake" variant="page" />;
  const gap = gapSource(overview.sources);
  return (
    <div className="work-intake">
      {notice ? <div className="work-note" role="status">{notice}</div> : null}
      <p className="admin-panel__hint">
        Which items flow from this Workspace's{" "}
        <button type="button" className="work-link" onClick={actions.onOpenConnectors}>connections</button> into Work.
      </p>
      <section className="admin-panel__card">
        <div className="admin-panel__section-header">
          <span>Sources of {workspaceName}</span>
          <span className="work-badge work-badge--neutral">{workSourcesSummary(overview.sources)}</span>
        </div>
        <div className="work-intake__overview" role="table" aria-label="Sources">
          <div className="work-intake__row work-intake__row--head" role="row">
            <span role="columnheader">Source</span><span role="columnheader">Connection</span>
            <span role="columnheader">In Knowledge</span><span role="columnheader">In Work</span><span />
          </div>
          {overview.sources.map((source) => (
            <SourceRow key={source.kind} source={source} actions={actions} />
          ))}
        </div>
      </section>
      {gap ? (
        <div className="work-gap" role="status">
          {gap.label} is connected and synced into Knowledge, but nothing flows into Work yet.{" "}
          <button type="button" className="work-link" onClick={() => actions.onSetUp(gap.kind)}>
            Set up {gap.label} intake
          </button>
        </div>
      ) : null}
      <section className="admin-panel__card" id="work-intake-list">
        <div className="admin-panel__section-header">
          <span>Intakes</span>
          <button type="button" className="admin-panel__action-btn" onClick={() => actions.onSetUp("")}>+ New intake</button>
        </div>
        {overview.intakes.length ? overview.intakes.map((intake) => (
          <IntakeCard key={intake.id} intake={intake} workspaceId={workspaceId} reloadKey={reload} actions={actions} />
        )) : <p className="admin-panel__hint">No intake yet. Set one up from a connected source above.</p>}
      </section>
      {setup ? (
        <WorkIntakeSetupDrawer workspaceId={workspaceId} workspaceName={workspaceName} sources={overview.sources}
          workflowMode={workflowModeOf(overview.intakes)}
          target={setup} onClose={() => setSetup(null)} onOpenConnectors={() => { setSetup(null); onOpenConnectors(); }}
          onDone={(text) => { setSetup(null); setNotice(text); setLocalReload((value) => value + 1); }} />
      ) : null}
    </div>
  );
}

function SourceRow({ source, actions }: { source: IntakeSource; actions: WorkIntakeActions }) {
  const connection = source.connections.length
    ? <><span className="work-intake__ok">✓</span> {source.connections.map(connectionLabel).join(", ")}</>
    : <span className="work-intake__no">✗ not connected</span>;
  const knowledge = knowledgeLabel(source);
  let work: JSX.Element;
  let action: JSX.Element | null = null;
  if (source.work_state === "not_a_work_source") {
    work = <span className="work-intake__off">not a work source</span>;
  } else if (source.work_state === "no_connection") {
    work = <span className="work-intake__off">–</span>;
    action = <button type="button" className="admin-panel__action-btn" onClick={actions.onOpenConnectors}>Connect</button>;
  } else if (source.work_state === "set_up") {
    work = <><span className="work-intake__ok">✓</span> {workLabel(source)}</>;
    action = (
      <button type="button" className="admin-panel__action-btn"
        onClick={() => document.getElementById("work-intake-list")?.scrollIntoView({ behavior: "smooth" })}>
        Open
      </button>
    );
  } else {
    work = <span className="work-intake__no">✗ no intake</span>;
    action = (
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
        onClick={() => actions.onSetUp(source.kind)}>
        Set up intake
      </button>
    );
  }
  return (
    <div className="work-intake__row" role="row" data-testid={`intake-source-${source.kind}`}>
      <span className="work-intake__source" role="cell">
        <ConnectorBrandIcon kind={source.kind} label={source.label} />
        <b>{source.label}</b>
      </span>
      <span role="cell">{connection}</span>
      <span role="cell">{knowledge ? <><span className="work-intake__ok">✓</span> {knowledge}</> : <span className="work-intake__off">–</span>}</span>
      <span role="cell">{work}</span>
      <span role="cell">{action}</span>
    </div>
  );
}

function IntakeCard({ intake, workspaceId, reloadKey, actions }: {
  intake: IntakeSummary;
  workspaceId: string;
  reloadKey?: string | number;
  actions: WorkIntakeActions;
}) {
  const connection = connectionLabel(intake.connection);
  const sync = cardSyncLabel(intake);
  return (
    <div className="work-detail__section work-intake__intake" data-testid="intake-card">
      <div className="work-intake__between">
        <div className="work-intake__source">
          <ConnectorBrandIcon kind={intake.source_type} label={sourceLabel(intake.source_type)} />
          <div>
            <div className="work-intake__name">{intake.name}</div>
            <div className="work-intake__sub">via {connection}{intake.connection.available ? "" : " (not available)"}</div>
          </div>
        </div>
        <div className="work-intake__actions">
          <span className={`work-badge ${intake.is_active ? "work-badge--active" : "work-badge--neutral"}`}>
            {intake.is_active ? "enabled" : "off"}
          </span>
          <button type="button" className="admin-panel__action-btn" onClick={() => actions.onPreview(intake)}>Preview</button>
          <button type="button" className="admin-panel__action-btn" onClick={() => actions.onEdit(intake)}>Edit</button>
        </div>
      </div>
      <div className="work-intake__kv">
        <div><b>What</b>{whatLabel(intake)}</div>
        <div><b>When</b>{scheduleLabel(intake.schedule)}</div>
        <div><b>How</b>{automationLabel(intake)}</div>
        <div data-testid="intake-card-sync"><b>Sync</b>{sync.text}{sync.own ? <span className="work-intake__muted">Set for this source</span> : null}</div>
        <div><b>Connection</b>{connection}</div>
      </div>
      <h3>Run history</h3>
      <WorkIntakeRunHistory workspaceId={workspaceId} intakeId={intake.id} reloadKey={reloadKey} />
    </div>
  );
}
