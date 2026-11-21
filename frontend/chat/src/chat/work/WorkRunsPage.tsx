import { useEffect, useState } from "react";

import { TimeText } from "../../admin/utils/TimeText";
import { LoadingState } from "../../layout/LoadingState";
import { StatusLabel } from "../../layout/StatusLabel";
import { readJson } from "../chatApiClient";
import { chatSessionHref, opensChat, SAMPLE_RUN_LABEL, SAMPLE_RUN_TEXT, sampleRunBadge } from "../workflowRun/workflowRunModel";
import { RunTokensPanel } from "../workflowRun/RunTokens";
import { SeatCell } from "../cost/SeatCell";
import { hasSeat, seatHeading, seatShort, seatSentence } from "../cost/seatEquivalent";
import {
  costText,
  resultText,
  runName,
  runSeat,
  runTone,
  splitRuns,
  statusWord,
  stepText,
  totalCost,
  totalSeat,
  waitingHeading,
  waitingText,
  runWorkflowTitle,
  workRunsPath,
  type WorkRunRow,
} from "./workRunsModel";

type WorkRunsPageProps = { projectId?: string | null; reloadKey?: string | number };

function WaitingRuns({ waiting }: { waiting: WorkRunRow[] }) {
  return (
    <section className="work-runs__waiting" aria-label="Waiting for you">
      <h2 className="work-runs__heading">{waitingHeading(waiting.length)}</h2>
      {waiting.map((run) => (
        <article className="work-runs__card" key={run.id} data-testid="work-runs-waiting">
          <div className="work-runs__card-main">
            <strong className="work-runs__name">{runName(run)}</strong>
            <span className="work-runs__why">{waitingText(run)}</span>
          </div>
          <StatusLabel label={statusWord(run)} tone={runTone(run)} />
          {run.cost ? <span className="work-runs__cost">API {costText(run.cost)}</span> : null}
          {hasSeat(runSeat(run)) ? (
            <span className="work-runs__cost" title={seatSentence(runSeat(run))}>{seatShort(runSeat(run))}</span>
          ) : null}
          {run.session_id ? (
            <a className="work-area__button work-area__button--primary" href={chatSessionHref(run.session_id)}>
              {run.status === "paused" ? "Open" : "Open decision"}
            </a>
          ) : null}
        </article>
      ))}
    </section>
  );
}

function RunRowCells({ run, onTokens }: { run: WorkRunRow; onTokens: (run: WorkRunRow) => void }) {
  return (
    <tr>
      <td>
        {run.session_id && opensChat(run) ? (
          <a className="work-runs__link" href={chatSessionHref(run.session_id)}>{runName(run)}</a>
        ) : <span>{runName(run)}</span>}
        {sampleRunBadge(run) ? (
          <>
            {" "}
            <span className="work-badge work-badge--info" title={SAMPLE_RUN_TEXT}>{SAMPLE_RUN_LABEL}</span>
          </>
        ) : null}
      </td>
      <td>{runWorkflowTitle(run)}</td>
      <td>
        <span className="work-runs__step">
          <StatusLabel label={statusWord(run)} tone={runTone(run)} />
          {stepText(run) ? <span>{stepText(run)}</span> : null}
        </span>
      </td>
      <td>
        {run.pull_request?.url ? (
          <a href={run.pull_request.url} target="_blank" rel="noreferrer">{resultText(run)}</a>
        ) : <span title={run.pull_request ? undefined : run.stop_reason ?? undefined}>{resultText(run)}</span>}
      </td>
      <td className="work-runs__num">{costText(run.cost)}</td>
      <td className="work-runs__num"><SeatCell figures={runSeat(run)} empty="–" /></td>
      <td><TimeText value={run.created_at ?? run.updated_at} fallback="–" /></td>
      <td>
        <button
          type="button"
          className="ds-btn ds-btn--sm"
          data-testid="work-runs-tokens"
          aria-label={`Tokens of ${runName(run)}`}
          onClick={() => onTokens(run)}
        >
          Tokens
        </button>
      </td>
    </tr>
  );
}

function RunsTable({ runs, onTokens }: { runs: WorkRunRow[]; onTokens: (run: WorkRunRow) => void }) {
  return (
    <div className="work-table-wrap">
      <table className="work-table work-runs__table">
        <thead>
          <tr>
            <th>Run</th>
            <th>Workflow</th>
            <th>Step</th>
            <th>Result</th>
            <th className="work-runs__num">API cost</th>
            <th className="work-runs__num">{seatHeading()}</th>
            <th>Started</th>
            <th><span className="ds-visually-hidden">Tokens</span></th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => <RunRowCells key={run.id} run={run} onTokens={onTokens} />)}
        </tbody>
      </table>
    </div>
  );
}

// Work › Runs: what waits for the person first, then every
// run with its step, result and cost. A row opens the run's chat, where the run card holds its actions; "Tokens"
// shows where the run's tokens went in a side panel, for everyone who may read the run.
export function WorkRunsPage({ projectId, reloadKey }: WorkRunsPageProps) {
  const [runs, setRuns] = useState<WorkRunRow[] | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [tokensOf, setTokensOf] = useState<WorkRunRow | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError("");
    void readJson<{ runs: WorkRunRow[] }>(workRunsPath(projectId))
      .then((payload) => !cancelled && setRuns(payload.runs || []))
      .catch((reason: unknown) => {
        if (cancelled) return;
        setRuns([]);
        setError(reason instanceof Error ? reason.message : "The runs could not be loaded.");
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, reloadKey, attempt]);

  if (runs === null) return <LoadingState label="runs" rows={5} onRetry={() => setAttempt((value) => value + 1)} />;

  const { waiting } = splitRuns(runs);
  const total = totalCost(runs);
  const seat = totalSeat(runs);

  return (
    <div className="work-runs" data-testid="work-runs">
      {error ? <div className="work-area__error">{error}</div> : null}

      {waiting.length ? <WaitingRuns waiting={waiting} /> : null}

      {runs.length === 0 && !error ? (
        <div className="work-empty">
          <div className="work-empty__eyebrow">Runs</div>
          <h2>No runs yet</h2>
          <p>Start a workflow from a work item or from the chat; its runs show here with step, result and cost.</p>
        </div>
      ) : null}

      {runs.length > 0 ? <RunsTable runs={runs} onTokens={setTokensOf} /> : null}

      {tokensOf ? <RunTokensPanel runId={tokensOf.id} title={runName(tokensOf)} onClose={() => setTokensOf(null)} /> : null}

      {total > 0 || hasSeat(seat) ? (
        <p className="work-runs__total" data-testid="work-runs-total">
          {total > 0 ? <span>API cost of these {runs.length} runs: ${total.toFixed(2)}.</span> : null}
          {hasSeat(seat) ? <span>{seatSentence(seat)}.</span> : null}
        </p>
      ) : null}
    </div>
  );
}
