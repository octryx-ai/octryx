// A Work item on the phone (phase A; run view): the ticket (state, people, labels,
// description), its change plan and comments, and its latest run as a summary that opens the run view, where the run
// is steered and its decisions are answered. A task without a running run can start one here.

import { useCallback, useEffect, useState } from "react";
import { formatDate } from "../admin/utils/dateTime";
import { StatusLabel } from "../layout/StatusLabel";
import { runPositionText } from "../chat/workflowRun/workflowRunModel";
import { runStatusLabel } from "../chat/workflowRun/workflowRunStatus";
import { type WorkflowRun } from "../chat/workflowRun/workflowRunTypes";
import { Icon } from "./icons";
import { loadRun, loadTask, loadTaskPlans } from "./mobileApi";
import { type MobileError } from "./mobileSession";
import { planStatusLabel, readTaskDetail, readTaskPlan, sourceLabel, stateLabel, type Case, type TaskDetail, type TaskPlan } from "./mobileTasksModel";
import { isFinished, runTone } from "./mobileRuns";
import { DetailHeader } from "./PageHeader";
import { useRefreshEvent } from "./pullToRefresh";
import { RunStart } from "./RunStart";

const POLL_MS = 10000;
const COMMENT_CHARS = 600;
// The task's detail and change plan (read once), and its shown run (polled, and on pull to refresh).
function useCaseData(item: Case) {
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [plan, setPlan] = useState<TaskPlan | null>(null);
  // The run shown: the task's newest, or the one just started here.
  const [runId, setRunId] = useState(item.run?.id ?? "");
  useEffect(() => {
    let alive = true;
    void loadTask(item.id)
      .then((raw) => alive && setDetail(readTaskDetail(raw)))
      .catch(() => undefined);
    void loadTaskPlans(item.id)
      .then((raw) => alive && setPlan(readTaskPlan(raw)))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [item.id]);

  const refresh = useCallback(async () => {
    if (!runId) return;
    try {
      setRun((await loadRun(runId)).run as WorkflowRun);
      setError("");
    } catch (reason) {
      setError((reason as MobileError).status === 404 ? "The run is not there any more." : "The run could not be loaded.");
    }
  }, [runId]);
  useRefreshEvent(refresh);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => !document.hidden && void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);
  return { run, error, detail, plan, runId, setRunId, refresh };
}

function CaseFacts({ item, workspace, detail }: { item: Case; workspace: string; detail: TaskDetail | null }) {
  const facts: [string, string][] = (
    [
      ["State", stateLabel(item.state)],
      ["Priority", item.priority ? item.priority[0].toUpperCase() + item.priority.slice(1) : ""],
      ["Type", detail?.issueType ? detail.issueType[0].toUpperCase() + detail.issueType.slice(1) : ""],
      ["Assignee", item.assignee],
      ["Reporter", item.reporter],
      ["Workspace", workspace],
      ["Source", sourceLabel(item.source)],
    ] as [string, string][]
  ).filter(([, value]) => value);
  return (
    <section className="m-panel" aria-label="Work item">
      <h2 className="m-item-title">{item.title}</h2>
      <dl className="m-facts">
        {facts.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {detail?.labels.length ? (
        <p className="m-labels">
          {detail.labels.map((label) => (
            <span key={label} className="m-tag">
              {label}
            </span>
          ))}
        </p>
      ) : null}
      {item.url && (
        <a className="m-link" href={item.url} target="_blank" rel="noreferrer">
          Open in {sourceLabel(item.source) || "the tracker"}
        </a>
      )}
    </section>
  );
}

function CaseRun({ run, onOpen }: { run: WorkflowRun; onOpen: () => void }) {
  return (
      <section aria-labelledby="m-case-run">
        <h2 id="m-case-run" className="m-section">
          Run
        </h2>
        <button type="button" className="m-run-card" onClick={onOpen}>
          <span className="m-run-card-text">
            <StatusLabel label={runStatusLabel(run)} tone={runTone(run.status)} />
            <span>{isFinished(run.status) ? run.title : runPositionText(run) || run.title}</span>
          </span>
          <Icon name="chevronRight" size={18} className="m-row-chevron" />
        </button>
      </section>
  );
}

function CasePlan({ plan }: { plan: TaskPlan | null }) {
  return (
    <section className="m-panel" aria-labelledby="m-case-plan">
      <h2 id="m-case-plan" className="m-section">
        Change plan
      </h2>
      {plan ? (
        <>
          <p>
            <b>{planStatusLabel(plan.status)}</b>
            <span className="m-muted">
              {" "}
              · Version {plan.version}
              {plan.acceptance ? ` · ${plan.acceptance} acceptance criteria` : ""}
            </span>
          </p>
          {plan.understood && <p className="m-muted">{plan.understood}</p>}
          {plan.openQuestions.length > 0 && (
            <>
              <p>
                <b>Open questions</b>
              </p>
              <ul className="m-list">
                {plan.openQuestions.map((question) => (
                  <li key={question}>{question}</li>
                ))}
              </ul>
            </>
          )}
        </>
      ) : (
        <p className="m-muted">No change plan yet.</p>
      )}
    </section>
  );
}

function CaseComments({ detail }: { detail: TaskDetail }) {
  return (
      <section className="m-panel" aria-labelledby="m-case-comments">
        <h2 id="m-case-comments" className="m-section">
          Comments <span className="m-count">{detail.commentsTotal}</span>
        </h2>
        {detail.comments.map((comment) => (
          <div key={comment.key} className="m-comment">
            <p className="m-muted">
              {[comment.author, comment.created && formatDate(comment.created)].filter(Boolean).join(" · ")}
            </p>
            <p>{comment.body.length > COMMENT_CHARS ? `${comment.body.slice(0, COMMENT_CHARS)}…` : comment.body}</p>
          </div>
        ))}
      </section>
  );
}

export function CasePage({
  item,
  workspace,
  onBack,
  onOpenRun,
}: {
  item: Case;
  workspace: string;
  onBack: () => void;
  onOpenRun: (runId: string, title: string) => void;
}) {
  const { run, error, detail, plan, runId, setRunId } = useCaseData(item);
  const subject = `${item.key} · ${item.title}`;

  return (
    <div className="m-screen">
      <DetailHeader title={item.key} subtitle={item.title} onBack={onBack} />
      <main className="m-body">
        <CaseFacts item={item} workspace={workspace} detail={detail} />

        {run && <CaseRun run={run} onOpen={() => onOpenRun(run.id, subject)} />}
        {error && (
          <p className="m-banner m-banner-problem" role="alert">
            {error}
          </p>
        )}
        {/* A finished run (completed, stopped, failed) never blocks the next one: the task can be started again. */}
        {(!runId || (run !== null && isFinished(run.status))) && (
          <RunStart item={item} issueType={detail?.issueType ?? ""} onStarted={(id) => {
            setRunId(id);
            onOpenRun(id, subject);
          }} />
        )}

        {detail?.description && (
          <details className="m-panel m-fold-panel">
            <summary>Description</summary>
            <p className="m-wrap-text">{detail.description}</p>
          </details>
        )}

        <CasePlan plan={plan} />

        {detail && detail.comments.length > 0 && <CaseComments detail={detail} />}
      </main>
    </div>
  );
}
