import { useEffect, useRef, useState } from "react";

import "./workItemsLean.css";
import { readJson } from "../chatApiClient";
import { chatSessionHref } from "../workflowRun/workflowRunModel";
import { startRunBody, startableWorkflowsPath, WORKFLOW_RUNS_PATH } from "../workflowRun/workflowRunRequests";
import { type StartableWorkflow } from "../workflowRun/workflowRunTypes";
import { readRuntimeTargetChoices, runtimeTargetsPath, type RuntimeTargetChoices } from "../workflowRun/runtimeTargetModel";
import { RunOnSelect } from "../workflowRun/RunOnSelect";
import { RunModelSelect } from "../workflowRun/RunModelSelect";
import { modelStartError, targetWithModel } from "../workflowRun/runModelModel";
import { INSTALL_LAUNCHER_HREF } from "../workflowRun/workflowRunModel";
import { useEffectiveEngine } from "../engines/useEffectiveEngine";
import { WorkItemLimitsFields } from "./WorkItemLimitsFields";
import { workflowsHref } from "./workTransitionModel";
import {
  ADVANCED_FIELDS,
  advancedOpen,
  chosenTarget,
  startRunBlockedReason,
  targetHelp,
} from "./workItemRunStartModel";
import type { WorkItem } from "./workItemTypes";

// The refusal of a workflow that builds or tests on the server (backend foreign_build_guard.SERVER_BUILD_NOT_ALLOWED).
const SERVER_BUILD_NOT_ALLOWED = "server_build_not_allowed";

function useRunStartState(item: WorkItem, focusOnOpen: boolean) {
  const workflowField = useRef<HTMLSelectElement | null>(null);
  const [startable, setStartable] = useState<StartableWorkflow[] | null>(null);
  const [workflowKey, setWorkflowKey] = useState("");
  const [repository, setRepository] = useState("");
  const [branch, setBranch] = useState("");
  const [targets, setTargets] = useState<RuntimeTargetChoices>({ options: [], default: "server" });
  const [targetKey, setTargetKey] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  // The server refused a build on the server: the refusal's way on is the launcher install page.
  const [needsDevice, setNeedsDevice] = useState(false);
  const [busy, setBusy] = useState(false);
  const [limitsSet, setLimitsSet] = useState(false);
  const engine = useEffectiveEngine(item.project_id);
  const [model, setModel] = useState("");
  const [modelError, setModelError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void readJson<{ workflows: StartableWorkflow[]; entry_workflow?: string | null }>(
      startableWorkflowsPath(item.project_id, item.id))
      .then((payload) => {
        if (cancelled) return;
        setStartable(payload.workflows);
        // The item's entry workflow (triage, or the incident analysis for an incident) is preselected, never started.
        if (payload.entry_workflow) setWorkflowKey((chosen) => chosen || (payload.entry_workflow ?? ""));
      })
      .catch(() => !cancelled && setStartable([]));
    // Where the run executes: the user's devices and folders, the default their last choice here.
    void readJson<unknown>(runtimeTargetsPath(item.project_id))
      .then((payload) => !cancelled && setTargets(readRuntimeTargetChoices(payload)))
      .catch(() => !cancelled && setTargets({ options: [], default: "server" }));
    return () => {
      cancelled = true;
    };
  }, [item.id, item.project_id]);

  const listed = Boolean(startable?.length);
  useEffect(() => {
    if (!focusOnOpen || !listed) return;
    workflowField.current?.focus({ preventScroll: true });
    workflowField.current?.scrollIntoView?.({ block: "nearest" });
  }, [focusOnOpen, listed]);
  return { workflowField, startable, workflowKey, setWorkflowKey, repository, setRepository, branch, setBranch, targets, targetKey,
    setTargetKey, problem, setProblem, needsDevice, setNeedsDevice, busy, setBusy, limitsSet, setLimitsSet, engine, model, setModel,
    modelError, setModelError };
}

type RunStartState = ReturnType<typeof useRunStartState>;

async function startRun(run: RunStartState, item: WorkItem, target: ReturnType<typeof chosenTarget>) {
  const { workflowKey, repository, branch, model, setBusy, setProblem, setNeedsDevice, setModelError } = run;
  setBusy(true);
  setProblem(null);
  setNeedsDevice(false);
  setModelError(null);
  try {
    const payload = await readJson<{ session_id: string }>(WORKFLOW_RUNS_PATH, {
      method: "POST",
      body: JSON.stringify(startRunBody(workflowKey, item.id, repository, branch,
        targetWithModel(target?.target ?? null, model))),
    });
    window.location.assign(chatSessionHref(payload.session_id));
  } catch (error) {
    const atModel = modelStartError(error);
    if (atModel) setModelError(atModel);
    else {
      setProblem(error instanceof Error ? error.message : "The run could not start.");
      setNeedsDevice((error as { code?: string | null } | null)?.code === SERVER_BUILD_NOT_ALLOWED);
    }
  } finally {
    setBusy(false);
  }
}

function RunStartFields({ run, item, startable, id, target, blockedReason, start }: {
  run: RunStartState; item: WorkItem; startable: StartableWorkflow[]; id: (name: string) => string;
  target: ReturnType<typeof chosenTarget>; blockedReason: string | null | undefined; start: () => Promise<void>;
}) {
  const { workflowField, workflowKey, setWorkflowKey, targets, targetKey, setTargetKey, engine, model, setModel, modelError,
    setModelError, busy } = run;
  return (
    <>
      <div className="admin-panel__field">
        <label htmlFor={id("start")}>Workflow</label>
        <select id={id("start")} ref={workflowField} className="admin-panel__input" value={workflowKey}
          onChange={(event) => setWorkflowKey(event.target.value)}>
          <option value="">Choose a workflow</option>
          {startable.map((workflow) => (
            <option key={workflow.key} value={workflow.key}>{workflow.title}</option>
          ))}
        </select>
      </div>
      <RunOnSelect id={id("target")} options={targets.options} value={targetKey || targets.default}
        onChange={setTargetKey} help={targetHelp(target)} />
      <RunModelSelect id={id("model")} projectId={item.project_id ?? ""} engine={engine} target={target?.target ?? null}
        value={model} error={modelError} onChange={(next) => { setModel(next); setModelError(null); }} />
      <div className="work-run-start__actions">
        <button type="button" data-testid="work-run-start-button"
          className={`work-area__button${blockedReason ? "" : " work-area__button--primary"}`}
          disabled={Boolean(blockedReason)} onClick={() => void start()}>
          Start run
        </button>
        {blockedReason && !busy ? (
          <span className="work-run-start__hint" data-testid="work-run-start-reason">{blockedReason}</span>
        ) : null}
      </div>
    </>
  );
}

// Start a workflow run for a Work Item: workflow and run location up front,
// "Start run" as the one primary action with its reason while disabled; repository, branch and run limits under
// "Advanced", each with a label, an example and one sentence. Opened by "Start workflow", the workflow field takes the
// focus (and comes into view) as soon as the list arrived (the form looked like a silent start).
export function WorkItemRunStart({ item, focusOnOpen = false }: { item: WorkItem; focusOnOpen?: boolean }) {
  const run = useRunStartState(item, focusOnOpen);
  const { startable, workflowKey, repository, setRepository, branch, setBranch, targets, targetKey, problem, needsDevice, busy,
    limitsSet, setLimitsSet } = run;

  const target = chosenTarget(targets, targetKey);
  const blockedReason = startRunBlockedReason(workflowKey, busy, item.project_id);

  async function start() {
    if (blockedReason) return;
    await startRun(run, item, target);
  }

  const id = (name: string) => `run-${name}-${item.id}`;
  return (
    <div className="work-run-start" data-testid="work-run-start">
      {startable && !startable.length ? (
        <p className="work-detail__empty" data-testid="work-run-start-none">
          No workflow can start for this item yet.{" "}
          <a href={workflowsHref(item.project_id)}>Publish one in Agents › Workflows</a>.
        </p>
      ) : null}
      {startable?.length ? (
        <RunStartFields run={run} item={item} startable={startable} id={id} target={target} blockedReason={blockedReason} start={start} />
      ) : null}
      <details className="work-run-start__advanced" data-testid="work-run-advanced"
        open={advancedOpen(repository, branch, limitsSet ? "set" : "") || undefined}>
        <summary>Advanced</summary>
        {startable?.length ? (
          <>
            <AdvancedField id={id("repository")} field={ADVANCED_FIELDS.repository} value={repository} onChange={setRepository} />
            <AdvancedField id={id("branch")} field={ADVANCED_FIELDS.branch} value={branch} onChange={setBranch} />
          </>
        ) : null}
        <WorkItemLimitsFields item={item} onHasValue={setLimitsSet} />
      </details>
      {problem ? <p className="work-detail__empty" role="alert">{problem}</p> : null}
      {/* Outsider walkthrough: the refusal named "Agents › Install octryx-claude" without a way there. */}
      {needsDevice ? (
        <p><a className="admin-panel__action-btn" href={INSTALL_LAUNCHER_HREF} data-testid="run-start-install-launcher">
          Install octryx-claude</a></p>
      ) : null}
    </div>
  );
}

function AdvancedField({ id, field, value, onChange }: {
  id: string;
  field: { label: string; hint: string; placeholder: string };
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="admin-panel__field">
      <label htmlFor={id}>{field.label}</label>
      <input id={id} className="admin-panel__input" value={value} placeholder={field.placeholder}
        type="text" onChange={(event) => onChange(event.target.value)} />
      <p className="work-run-start__hint">{field.hint}</p>
    </div>
  );
}
