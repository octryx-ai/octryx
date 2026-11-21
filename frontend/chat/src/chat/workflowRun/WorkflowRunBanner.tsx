import { useEffect, useState } from "react";

import "./workflowRun.css";
import { StatusLabel } from "../../layout/StatusLabel";
import { composerTargetOf } from "./runtimeTargetModel";
import { readExecutionTarget, setExecutionTarget } from "../devices/executionTarget";
import { useWorkflowRun } from "./useWorkflowRun";
import { RunDetails } from "./RunDetails";
import { decisionCard } from "./decisionCardModel";
import { workSummary } from "./teamworkModel";
import { publishRunThreadTitle, rememberRunBarOpen, runActsAtOnce, runBarOpen, runPhaseShort, runPlaceText, runWorkflowName } from "./runBarModel";
import { runNextAction, runStateTone, runThreadTitle } from "./runCardModel";
import { chatSessionHref, FOLLOW_UP_NOT_STARTED, followUpFailure, SAMPLE_RUN_LABEL, SAMPLE_RUN_TEXT, sampleRunBadge } from "./workflowRunModel";
import { runStatusLabel } from "./workflowRunStatus";
import { TEST_ALERT_TEXT } from "./workflowRunPayloadView";
import { type RunAction, type RunActionValue } from "./workflowRunTypes";

type WorkflowRunBannerProps = {
  sessionId: string | null | undefined;
  refreshKey: unknown;
};

function sessionStore(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.sessionStorage : null;
  } catch {
    return null;
  }
}

// The run bar above a run's chat (product inventory): one quiet line "Workflow · Phase n/m · State ·
// Where", the next action as one small button at its end, everything else folded into the details below it
// (collapsed by default, remembered per run for this browser tab). It loads after the messages and never blocks them.
export function WorkflowRunBanner({ sessionId, refreshKey }: WorkflowRunBannerProps) {
  const { run, busy, problem, act } = useWorkflowRun(sessionId, refreshKey);
  const [inputs, setInputs] = useState<Record<string, number | string>>({});
  const [openRuns, setOpenRuns] = useState<Record<string, boolean>>({});
  const runtimeTarget = run?.runtime_target;
  useEffect(() => {
    // A device run's thread sends from the run's device and folder (the server refuses any other target).
    const target = composerTargetOf(runtimeTarget);
    const current = readExecutionTarget(sessionId);
    const same = current.kind === "device" && target?.kind === "device" && current.deviceId === target.deviceId
      && current.folder === target.folder;
    if (target && sessionId && !same) setExecutionTarget(sessionId, target);
  }, [runtimeTarget, sessionId]);
  const threadTitle = run ? runThreadTitle(run) : null;
  useEffect(() => {
    // The chat header shows the Work item and the current state instead of the thread's first prompt.
    publishRunThreadTitle(sessionId, threadTitle);
  }, [sessionId, threadTitle]);
  if (!run) return null;

  // A product owner's decision opens the card by itself: it is the reason the run waits.
  const deciding = decisionCard(run.waiting) !== null;
  const open = openRuns[run.id] ?? (deciding || runBarOpen(sessionStore(), run.id));
  const nextAction = runNextAction(run);
  const objectName = run.work_item ? `${run.work_item.key} ${run.work_item.title}`.trim() : run.title;
  const detailsId = `run-bar-details-${run.id}`;
  // On a Parallel work box the line says how the split stands ("4 items · 2 running").
  const split = run.current_node?.kind === "parallel_work" && run.status !== "completed" ? workSummary(run.work) : "";
  const parts = [runWorkflowName(run), runPhaseShort(run), split].filter(Boolean);
  const place = runPlaceText(run.runtime_target);

  function setOpen(next: boolean) {
    if (!run) return;
    rememberRunBarOpen(sessionStore(), run.id, next);
    setOpenRuns((current) => ({ ...current, [run.id]: next }));
  }

  function valueOf(action: RunAction) {
    return action.input ? (inputs[action.key] ?? action.input.default) : null;
  }

  async function choose(action: RunAction, value?: RunActionValue) {
    const result = await act(action, value ?? valueOf(action));
    if (action.key === "resume_in_new_session" && result?.session_id) {
      window.location.assign(chatSessionHref(result.session_id));
    }
  }

  return (
    <div className="workspace__feed-banner">
      <aside className="run-bar" aria-live="polite" aria-label="Workflow run" data-testid="workflow-run-bar">
        <div className="run-bar__line">
          <button
            type="button"
            className="run-bar__toggle"
            aria-expanded={open}
            aria-controls={detailsId}
            title={open ? "Hide run details" : "Show run details"}
            data-testid="workflow-run-bar-toggle"
            onClick={() => setOpen(!open)}
          >
            <span className="run-bar__chevron" aria-hidden="true">{open ? "▾" : "▸"}</span>
            <span className="run-bar__summary" title={parts.join(" · ")}>{parts.join(" · ")}</span>
          </button>
          <StatusLabel label={runStatusLabel(run)} tone={runStateTone(run)} testId="workflow-run-bar-state" />
          {run.test_alert ? <StatusLabel label="Test alert" tone="attention" title={TEST_ALERT_TEXT} /> : null}
          {followUpFailure(run) ? (
            <StatusLabel label={FOLLOW_UP_NOT_STARTED} tone="attention" title={followUpFailure(run)?.text}
              testId="workflow-run-follow-up-label" />
          ) : null}
          {sampleRunBadge(run) ? (
            <StatusLabel label={SAMPLE_RUN_LABEL} tone="info" title={SAMPLE_RUN_TEXT} testId="workflow-run-sample" />
          ) : null}
          {place ? <span className="run-bar__place" title={place} data-testid="workflow-run-bar-place">{place}</span> : null}
          {nextAction && !(deciding && open) ? (
            <button
              type="button"
              className="work-area__button work-area__button--primary run-bar__next"
              data-testid="workflow-run-next-action"
              disabled={busy}
              onClick={() => (runActsAtOnce(nextAction) && !deciding ? void choose(nextAction) : setOpen(true))}
            >
              {nextAction.label}
            </button>
          ) : null}
        </div>
        {open ? (
          <RunDetails
            run={run}
            id={detailsId}
            objectName={objectName}
            inputs={inputs}
            setInput={(key, value) => setInputs((current) => ({ ...current, [key]: value }))}
            valueOf={valueOf}
            busy={busy}
            onChoose={(action, value) => void choose(action, value)}
          />
        ) : null}
        {problem ? <div className="workspace__error">{problem}</div> : null}
      </aside>
    </div>
  );
}
