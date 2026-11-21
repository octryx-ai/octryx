import { useCallback, useEffect, useState } from "react";

import { approvalDetailHref } from "../../../chat/approval/approvalDetailModel";
import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import { DecisionDrawer } from "./DecisionDrawer";
import {
  DECISION_OUTCOMES,
  decisionOutcomeLabel,
  decisionsQuery,
  decisionTone,
  GATE_LABELS,
  gateLabel,
  readDecisionParams,
  type DecisionItem,
  type DecisionPage,
  type DecisionsToday,
} from "./decisionsModel";
import { Badge, Segmented, WorkspaceSelect, type ProjectOption } from "./obUi";
import { formatCount, formatTime, readErrorMessage } from "./obFormat";
import { Pager } from "./obPager";
import { RunDrawer } from "./RunDrawer";
import "./observability.css";

type Props = { projects: ProjectOption[]; readJson: ReadJsonFn };

const WINDOWS = [
  { value: 24, label: "24 h" },
  { value: 168, label: "7 d" },
  { value: 720, label: "30 d" },
];

// Observability → Decisions: the "was it allowed" timeline of every gate. Allows are counted, not listed.
export function ObservabilityDecisionsPage({ projects, readJson }: Props) {
  const [initial] = useState(() => readDecisionParams(typeof window === "undefined" ? "" : window.location.search));
  const [windowHours, setWindowHours] = useState(168);
  const [outcome, setOutcome] = useState(initial.outcome);
  const [gate, setGate] = useState("");
  const [workspaceId, setWorkspaceId] = useState("");
  const [policyId, setPolicyId] = useState(initial.policy);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<DecisionPage | null>(null);
  const [today, setToday] = useState<DecisionsToday | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openDecision, setOpenDecision] = useState<string | null>(initial.decision);
  const [openRun, setOpenRun] = useState<string | null>(null);

  const load = useCallback(
    () => loadDecisions(readJson, { windowHours, outcome, gate, workspaceId, policyId, page }, { setData, setToday, setError }),
    [readJson, windowHours, outcome, gate, workspaceId, policyId, page],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const filter = (apply: () => void) => {
    apply();
    setPage(1);
  };
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="ob-page" data-testid="observability-decisions">
      <DecisionFilters projects={projects} outcome={outcome} workspaceId={workspaceId} gate={gate} windowHours={windowHours}
        onOutcome={(value) => filter(() => setOutcome(value))} onWorkspace={(value) => filter(() => setWorkspaceId(value))}
        onGate={(value) => filter(() => setGate(value))} onWindow={(value) => filter(() => setWindowHours(value))} />
      <div className="ob-muted">
        Every non-allow outcome of every gate, plus the approval lifecycle. Allows are counted, not listed:{" "}
        <b>{today ? `${formatCount(today.allowed)} allowed today` : "…"}</b>.
      </div>
      {policyId ? <PolicyNote policyId={policyId} onShowAll={() => filter(() => setPolicyId(""))} /> : null}
      {error ? <div className="ob-warn" role="alert">{error}</div> : null}
      <DecisionsTable data={data} onOpen={setOpenDecision} />
      <div className="ob-between">
        <span className="ob-muted">{data ? `${data.total} decisions in the window` : ""}</span>
        <Pager page={page} pages={pages} onPage={setPage} />
      </div>
      {openDecision ? (
        <DecisionDrawer decisionId={openDecision} readJson={readJson} onClose={() => setOpenDecision(null)}
          onOpenRun={(runKey) => { setOpenDecision(null); setOpenRun(runKey); }} />
      ) : null}
      {openRun ? <RunDrawer runKey={openRun} readJson={readJson} onClose={() => setOpenRun(null)} /> : null}
    </div>
  );
}

// The list and today's counts, read together.
async function loadDecisions(readJson: ReadJsonFn, query: Parameters<typeof decisionsQuery>[0], set: {
  setData: (data: DecisionPage) => void;
  setToday: (today: DecisionsToday) => void;
  setError: (error: string | null) => void;
}) {
  try {
    const [list, counts] = await Promise.all([
      readJson<DecisionPage>(decisionsQuery(query)),
      readJson<DecisionsToday>("/api/v1/observability/decisions/today"),
    ]);
    set.setData(list);
    set.setToday(counts);
    set.setError(null);
  } catch (loadError) {
    set.setError(readErrorMessage(loadError, "Decisions could not be loaded."));
  }
}

function PolicyNote({ policyId, onShowAll }: { policyId: string; onShowAll: () => void }) {
  return (
    <div className="ob-note">
      Showing the decisions of policy <span className="admin-policy-inline-code">{policyId}</span>.{" "}
      <button type="button" className="ob-link" onClick={onShowAll}>Show all</button>
    </div>
  );
}

function DecisionsTable({ data, onOpen }: { data: DecisionPage | null; onOpen: (decisionId: string) => void }) {
  return (
    <table className="admin-panel__table ob-cards">
      <thead>
        <tr><th>Time</th><th>Outcome</th><th>What</th><th>Who · where</th><th>Gate</th><th>Deciding rule</th></tr>
      </thead>
      <tbody>
        {(data?.items ?? []).map((item) => <DecisionRow key={item.id} item={item} onOpen={() => onOpen(item.id)} />)}
        {data && !data.items.length ? (
          <tr><td colSpan={6} className="admin-panel__cell--muted">No decisions match. Allowed requests are counted, not listed.</td></tr>
        ) : null}
      </tbody>
    </table>
  );
}

function DecisionFilters({ projects, outcome, workspaceId, gate, windowHours, onOutcome, onWorkspace, onGate, onWindow }: {
  projects: ProjectOption[];
  outcome: string;
  workspaceId: string;
  gate: string;
  windowHours: number;
  onOutcome: (value: string) => void;
  onWorkspace: (value: string) => void;
  onGate: (value: string) => void;
  onWindow: (value: number) => void;
}) {
  return (
    <div className="ob-toolbar ob-toolbar--filters">
      <Segmented label="Outcome" value={outcome} onChange={onOutcome}
        options={["", ...DECISION_OUTCOMES].map((item) => ({ value: item, label: item ? decisionOutcomeLabel(item) : "All" }))} />
      <WorkspaceSelect projects={projects} value={workspaceId} onChange={onWorkspace} />
      <select className="admin-users__toolbar-select" aria-label="Gate" value={gate}
        onChange={(event) => onGate(event.target.value)}>
        <option value="">All gates</option>
        {Object.entries(GATE_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select>
      <Segmented label="Window" options={WINDOWS} value={windowHours} onChange={onWindow} />
    </div>
  );
}

function DecisionRow({ item, onOpen }: { item: DecisionItem; onOpen: () => void }) {
  return (
    <tr className="ob-row-button" tabIndex={0} onClick={onOpen}
      onKeyDown={(event) => { if (event.key === "Enter") onOpen(); }}>
      <td data-label="Time" className="ob-nowrap">{formatTime(item.time)}</td>
      <td data-label="Outcome"><Badge tone={decisionTone(item.outcome)}>{decisionOutcomeLabel(item.outcome)}</Badge></td>
      <td data-label="What">
        {item.what}
        {item.approval_id ? (
          <>
            {" "}
            <a className="ob-approval-link" href={approvalDetailHref(item.approval_id)} data-testid="decision-approval-link"
              onClick={(event) => event.stopPropagation()}>Approval ›</a>
          </>
        ) : null}
        {item.subtitle ? <div className="ob-muted">{item.subtitle}</div> : null}
      </td>
      <td data-label="Who · where" className="admin-panel__cell--muted">
        {item.decided_by ? `${decisionOutcomeLabel(item.outcome)} by ${item.decided_by}` : item.who} · {item.workspace_name ?? "global"}
      </td>
      <td data-label="Gate">{gateLabel(item.gate)}</td>
      <td data-label="Deciding rule" className="admin-panel__cell--muted">{item.rule ?? "–"}</td>
    </tr>
  );
}
