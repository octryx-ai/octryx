// Sections of the phone's run page: state and facts, Parallel work, steps, tasks and the links to chat and Work item.
import { StatusLabel } from "../layout/StatusLabel";
import { runPlaceText } from "../chat/workflowRun/runBarModel";
import { taskProgress, taskState } from "../chat/workflowRun/taskListModel";
import { workItemRows, workSummary } from "../chat/workflowRun/teamworkModel";
import { runGateText, runPositionText, runStopText, runUsageText } from "../chat/workflowRun/workflowRunModel";
import { runStatusLabel, pauseTitle } from "../chat/workflowRun/workflowRunStatus";
import { Icon } from "./icons";
import { readResponsible, responsibleText } from "./mobileTasksModel";
import { shortTime } from "./mobileUsageModel";
import { runTimeline, runTone, stepKindLabel } from "./mobileRuns";
import { runLineText, workflowRunLine } from "./engineSeatModel";
import type { RunPayload } from "./useRunPage";
import type { RunLinks } from "./RunPage";

export function RunSummary({ run, finished }: { run: RunPayload; finished: boolean }) {
  const responsible = readResponsible(run.responsible);
  const line = workflowRunLine(run as { engine?: unknown; route?: unknown });
  return (
    <section className="m-panel m-run-summary" aria-label="State">
      <div className="m-run-state">
        <StatusLabel label={runStatusLabel(run)} tone={runTone(run.status)} />
        <span className="m-when">{shortTime(run.updated_at ?? "")}</span>
      </div>
      {line && (
        <p className="m-muted" data-testid="m-run-line">
          {runLineText(line)}
        </p>
      )}
      {runPositionText(run) && !finished && <p className="m-run-position">{runPositionText(run)}</p>}
      {run.pause?.detail && <p className="m-muted">{run.pause.detail}</p>}
      {run.status === "paused" && run.pause_reason && !run.pause?.detail && (
        <p className="m-muted">{pauseTitle(run.pause_reason, run.pause)}</p>
      )}
      {runStopText(run) && <p className="m-muted">{runStopText(run)}</p>}
      {run.last_error && <p className="m-error">{run.last_error}</p>}
      <dl className="m-facts">
        {[
          ["Checks", runGateText(run)],
          ["Branch", run.branch ?? ""],
          ["Runs", runPlaceText(run.runtime_target)],
          ["Responsible", responsible ? responsibleText(responsible) : ""],
          ["Usage", runUsageText(run.model_usage)],
        ]
          .filter(([, value]) => value)
          .map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
      </dl>
    </section>
  );
}

export function RunParallelWork({ run, links }: { run: RunPayload; links: RunLinks }) {
  return (
    <section aria-labelledby="m-parallel">
      <h2 id="m-parallel" className="m-section">
        Parallel work
      </h2>
      <p className="m-section-hint">{workSummary(run.work)}</p>
      <ul className="m-rows m-group">
        {workItemRows(run.work).map((item) => (
          <li key={item.id}>
            <button
              type="button"
              className="m-row m-row-work"
              disabled={!item.sessionId}
              onClick={() => item.sessionId && links.onOpenChat(item.sessionId, item.title, run.project_id ?? "")}
            >
              <span className="m-row-text">
                <b>{item.title}</b>
                <span>{[item.role, item.model, item.round].filter(Boolean).join(" · ")}</span>
                {(item.after || item.detail) && (
                  <span className={item.tone === "problem" ? "m-row-problem" : undefined}>
                    {item.detail || item.after}
                  </span>
                )}
              </span>
              <StatusLabel label={item.label} tone={item.tone} />
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function RunSteps({ run }: { run: RunPayload }) {
  const steps = runTimeline(run);
  const done = steps.filter((step) => step.state === "done").length;
  if (steps.length === 0) return null;
  return (
    <section aria-labelledby="m-steps">
      <h2 id="m-steps" className="m-section">
        Steps <span className="m-count">{`${done}/${steps.length}`}</span>
      </h2>
      <ol className="m-timeline">
        {steps.map((step) => (
          <li key={step.id} className={`m-timeline-step m-timeline-${step.state}`}>
            <span className="m-timeline-mark" aria-hidden="true">
              {step.state === "done" && <Icon name="check" size={12} />}
            </span>
            <span className="m-timeline-text">
              <b>{step.title}</b>
              <span>
                {stepKindLabel(step.kind)}
                {step.state === "current" ? " · running now" : step.state === "waiting" ? " · waiting for you" : ""}
                {step.state === "problem" ? " · stopped here" : ""}
              </span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function RunTasks({ tasks }: { tasks: NonNullable<RunPayload["task_list"]> }) {
  return (
    <section aria-labelledby="m-tasks">
      <h2 id="m-tasks" className="m-section">
        Tasks
      </h2>
      <p className="m-section-hint">{taskProgress(tasks)}</p>
      <ul className="m-rows m-group">
        {tasks.map((task) => {
          const state = taskState(task, tasks);
          return (
            <li key={task.id} className="m-task">
              <span className={`m-task-mark${state.mark === "check" ? " m-task-done" : ""}`} aria-hidden="true">
                {state.mark === "check" ? <Icon name="check" size={14} /> : task.id}
              </span>
              <span className="m-row-text">
                <b className="m-wrap">{task.text}</b>
                {state.mark === "label" && <StatusLabel label={state.label} tone={state.tone} />}
                {task.note && <span>{task.note}</span>}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
