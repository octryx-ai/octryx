// The phone's start card of a phased workflow: Work item draft, Jira line, steps, repository, runs on, model and Start.
import { useEffect, useState, type ReactNode } from "react";

import { OTHER_WORKFLOW_LABEL } from "../chat/composer/automaticWorkflow";
import {
  jiraProblemText,
  repositoryBlockedReason,
  runOnHelp,
  startButtonLabel,
  startedLinkLabel,
  type WorkflowStartRepository,
} from "../chat/run/workflowStartModel";
import { runOnTarget } from "../chat/run/startCardChoices";
import { useEffectiveEngine } from "../chat/engines/useEffectiveEngine";
import { useRunModelChoices } from "../chat/workflowRun/RunModelSelect";
import type { PhoneProposal } from "./workflowProposalPhone";

export function PhoneStartCard({ card, projectId, busy, error, onAnswer, onOther, onOpenRun, children }: {
  card: Extract<PhoneProposal, { kind: "start" }>;
  projectId: string;
  busy: string | null;
  error: string;
  onAnswer: (decision: string, extra?: { runOn?: string; repository?: string; model?: string }) => Promise<void>;
  onOther: () => void;
  onOpenRun?: (runId: string, title: string) => void;
  children: ReactNode;
}) {
  const { view, decided } = card;
  const { runOn, setRunOn, repository, setRepository, model, setModel, models } = usePhoneStartChoices(view, projectId);
  const { item, outcome } = view;
  const started = outcome.kind === "started" ? outcome : null;
  const failed = outcome.kind === "error" ? outcome : null;
  const skipped = decided === "skip";
  const actionable = !started && !skipped && (decided !== "apply" || Boolean(failed));
  const progress = started ?? failed;
  const blocked = repositoryBlockedReason(view.repository, repository);
  const help = runOnHelp(view.runOn, runOn);
  const runTitle = [started?.itemKey, item.title].filter(Boolean).join(" · ") || view.workflowTitle;

  return (
    <section
      className={`m-approval m-proposal m-start${started ? " m-start-done" : failed ? " m-start-failed" : skipped ? " m-start-quiet" : ""}`}
      aria-label="Start a workflow" data-testid="m-workflow-start">
      <span className="m-eyebrow">{started ? "Workflow started" : "Start a workflow"}</span>
      <h2>{view.summary}</h2>
      {card.reason && !started && <p className="m-muted">{card.reason}</p>}

      <StartItem view={view} progress={progress} />

      {view.jiraLabel && !progress?.jiraKey && !progress?.jiraProblem && <p className="m-start-jira">{view.jiraLabel}</p>}
      <StartSteps view={view} />

      {view.repository && (
        <PhoneRepository repository={view.repository} value={repository} onChange={setRepository} editable={actionable}
          disabled={busy !== null} problem={error} />
      )}

      {actionable && view.runOn.options.length > 0 && <RunOnChoice view={view} runOn={runOn} setRunOn={setRunOn} help={help} disabled={busy !== null} />}
      {actionable && view.runOn.options.length > 0 && <ModelChoice model={model} setModel={setModel} models={models} disabled={busy !== null} />}

      <StartOutcome view={view} decided={decided} runTitle={runTitle} onOpenRun={onOpenRun} />

      {actionable && (
        <StartButtons busy={busy} blocked={blocked} outcome={outcome} onOther={onOther} onAnswer={onAnswer}
          onStart={() => void onAnswer("apply", { ...(runOn ? { runOn } : {}), ...(repository ? { repository } : {}), ...(model ? { model } : {}) })} />
      )}
      {error && !view.repository && <p className="m-error" role="alert">{error}</p>}
      {children}
    </section>
  );
}

type StartView = Extract<PhoneProposal, { kind: "start" }>["view"];
type StartProgress = Extract<StartView["outcome"], { kind: "started" | "error" }> | null;

// Runs on, repository and model as chosen on the card; a new workflow on the card starts the choices over.
function usePhoneStartChoices(view: StartView, projectId: string) {
  const [runOn, setRunOn] = useState(view.runOn.selected);
  const [repository, setRepository] = useState("");
  const [model, setModel] = useState("");
  const engine = useEffectiveEngine(view.projectId ?? projectId);
  const models = useRunModelChoices(view.projectId ?? projectId, engine, runOnTarget(runOn), model, setModel);
  useEffect(() => setRunOn(view.runOn.selected), [view.workflowKey, view.runOn.selected]);
  useEffect(() => setRepository(""), [view.workflowKey]);
  return { runOn, setRunOn, repository, setRepository, model, setModel, models };
}

function StartSteps({ view }: { view: StartView }) {
  return (
    <>
      {view.steps.length > 0 && (
        <ol className="m-start-steps" aria-label="Steps">
          {view.steps.map((step, index) => (
            <li key={`${index}-${step}`}>{step}</li>
          ))}
        </ol>
      )}
      {view.notes.map((note) => (
        <p key={note} className="m-muted">{note}</p>
      ))}
    </>
  );
}

// What the start did: refused with its reason, started with a link to the run, or still starting.
function StartOutcome({ view, decided, runTitle, onOpenRun }: {
  view: StartView; decided: "apply" | "skip" | null; runTitle: string; onOpenRun?: (runId: string, title: string) => void;
}) {
  const { outcome } = view;
  const started = outcome.kind === "started" ? outcome : null;
  const failed = outcome.kind === "error" ? outcome : null;
  const skipped = decided === "skip";
  const progress = started ?? failed;
  return (
    <>
      {failed && <p className="m-error" role="alert">{`${view.workflowTitle} did not start: ${failed.reason}`}</p>}
      {started && (
        started.runId && onOpenRun ? (
          <button type="button" className="m-primary m-wide" onClick={() => onOpenRun(started.runId!, runTitle)}>
            {startedLinkLabel(started)}
          </button>
        ) : (
          <a className="m-primary m-wide m-link-button" href={started.href}>
            {startedLinkLabel(started)}
          </a>
        )
      )}
      {progress?.jiraProblem && <p className="m-muted">{jiraProblemText(progress.jiraProblem)}</p>}
      {skipped && <p className="m-muted">Not started.</p>}
      {decided === "apply" && !started && !failed && <p className="m-muted">Starting…</p>}
    </>
  );
}

// The Work item the run works on: new or existing, its keys, title and description.
function StartItem({ view, progress }: { view: StartView; progress: StartProgress }) {
  const { item } = view;
  return (
    <div className="m-start-item">
      <span className="m-start-meta">
        <b>{item.mode === "new" ? `New ${item.typeLabel}` : item.typeLabel}</b>
        {item.key && <code>{item.key}</code>}
        {!item.key && progress?.itemKey && <code>{progress.itemKey}</code>}
        {progress?.jiraKey && progress.jiraKey !== item.key && <code data-testid="m-workflow-start-jira-key">{progress.jiraKey}</code>}
        {view.jiraProject && !view.jiraLabel && <span>Jira project {view.jiraProject}</span>}
      </span>
      {item.title && <strong>{item.title}</strong>}
      {item.mode === "new" && item.description &&
        (item.longDescription ? (
          <details>
            <summary className="m-muted">Description</summary>
            <p>{item.description}</p>
          </details>
        ) : (
          <p>{item.description}</p>
        ))}
    </div>
  );
}

function RunOnChoice({ view, runOn, setRunOn, help, disabled }: {
  view: StartView; runOn: string; setRunOn: (value: string) => void; help: string | null; disabled: boolean;
}) {
  return (
    <div className="m-run-start m-start-run-on">
      <label>
        <span>Runs on</span>
        <select value={runOn} disabled={disabled} onChange={(event) => setRunOn(event.target.value)}>
          {view.runOn.options.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      {help && <p className="m-muted">{help}</p>}
    </div>
  );
}

function ModelChoice({ model, setModel, models, disabled }: {
  model: string; setModel: (value: string) => void; models: ReturnType<typeof useRunModelChoices>; disabled: boolean;
}) {
  return (
    <div className="m-run-start m-start-run-on">
      <label>
        <span>Model</span>
        <select value={model} disabled={disabled || models.disabled} data-testid="m-workflow-start-model"
          onChange={(event) => setModel(event.target.value)}>
          {models.options.map((option) => (
            <option key={option.value || "auto"} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      {models.line && <p className="m-muted">{models.line}</p>}
      {models.hint && <p className="m-muted">{models.hint}</p>}
    </div>
  );
}

function StartButtons({ busy, blocked, outcome, onOther, onAnswer, onStart }: {
  busy: string | null; blocked: string | null; outcome: StartView["outcome"]; onOther: () => void;
  onAnswer: (decision: string) => Promise<void>; onStart: () => void;
}) {
  return (
    <div className="m-buttons">
      <button
        type="button"
        className="m-primary m-wide"
        disabled={busy !== null || Boolean(blocked)}
        onClick={onStart}
      >
        {busy === "apply" ? "Starting…" : startButtonLabel(outcome)}
      </button>
      {blocked && <p className="m-muted m-wide m-start-blocked">{blocked}</p>}
      <button type="button" disabled={busy !== null} onClick={onOther}>
        {OTHER_WORKFLOW_LABEL}
      </button>
      <button type="button" disabled={busy !== null} onClick={() => void onAnswer("skip")}>
        {busy === "skip" ? "Sending…" : "Don't start"}
      </button>
    </div>
  );
}

// The repository the run works in: a known one with its source and "Change", or a required choice. A refused start
// (409 missing repository, 422 not offered) stands here, at the choice.
function PhoneRepository({
  repository,
  value,
  onChange,
  editable,
  disabled,
  problem,
}: {
  repository: WorkflowStartRepository;
  value: string;
  onChange: (id: string) => void;
  editable: boolean;
  disabled: boolean;
  problem: string;
}) {
  const [changing, setChanging] = useState(false);
  const known = repository.name;
  const chosen = repository.options.find((option) => option.id === value);
  const choosing = editable && (!known || changing) && repository.options.length > 0;
  return (
    <div className="m-start-repository" data-testid="m-workflow-start-repository">
      {choosing ? (
        <div className="m-run-start m-start-run-on">
          <label>
            <span>Repository</span>
            <select value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
              {(!known || !repository.id) && <option value="">{known ?? "Choose a repository"}</option>}
              {repository.options.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.name}
                </option>
              ))}
            </select>
          </label>
        </div>
      ) : (
        <p className="m-start-repo-line">
          <span className="m-muted">Repository:</span> <b>{chosen?.name ?? known ?? "none yet"}</b>
          {(chosen ? "chosen by you" : repository.sourceText) && (
            <span className="m-muted"> · {chosen ? "chosen by you" : repository.sourceText}</span>
          )}
          {editable && known && repository.options.length > (repository.id ? 1 : 0) && (
            <button type="button" className="m-text-button" disabled={disabled} onClick={() => setChanging(true)}>
              Change
            </button>
          )}
        </p>
      )}
      {problem && <p className="m-error" role="alert">{problem}</p>}
    </div>
  );
}
