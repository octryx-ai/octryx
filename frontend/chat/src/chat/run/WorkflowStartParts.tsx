// Parts of the workflow start card: the Work item, the run choices, the outcome lines and the decision buttons.
import { RunOnSelect } from "../workflowRun/RunOnSelect";
import { StartModelBudget } from "./StartModelBudget";
import { StartRepository } from "./StartRepository";
import type { WorkflowStartCardState } from "./useWorkflowStartCard";
import {
  jiraProblemText,
  runOnHelp,
  startButtonLabel,
  startedLinkLabel,
  type WorkflowStartOutcome,
  type WorkflowStartView,
} from "./workflowStartModel";

type Started = Extract<WorkflowStartOutcome, { kind: "started" }>;
type Failed = Extract<WorkflowStartOutcome, { kind: "error" }>;

function ItemKey({ itemKey, href }: { itemKey: string; href: string | null }) {
  return href ? (
    <a className="workflow-start__key" href={href}>{itemKey}</a>
  ) : (
    <span className="workflow-start__key">{itemKey}</span>
  );
}

function ItemDescription({ item }: { item: WorkflowStartView["item"] }) {
  return item.longDescription ? (
    <details className="workflow-start__description">
      <summary>Description</summary>
      <p>{item.description}</p>
    </details>
  ) : (
    <p className="workflow-start__description">{item.description}</p>
  );
}

export function WorkflowStartItem({ view, progress }: { view: WorkflowStartView; progress: Started | Failed | null }) {
  const { item } = view;
  return (
    <div className="workflow-start__item">
      <div className="workflow-start__item-meta">
        <span className="workflow-start__type">{item.mode === "new" ? `New ${item.typeLabel}` : item.typeLabel}</span>
        {item.key ? <ItemKey itemKey={item.key} href={item.href} /> : null}
        {progress?.itemKey && !item.key ? <ItemKey itemKey={progress.itemKey} href={progress.itemHref} /> : null}
        {progress?.jiraKey && progress.jiraKey !== item.key ? <span className="workflow-start__key" data-testid="workflow-start-jira-key">{progress.jiraKey}</span> : null}
        {view.jiraProject && !view.jiraLabel ? <span className="workflow-start__meta">Jira project {view.jiraProject}</span> : null}
      </div>
      {item.title ? <p className="workflow-start__item-title">{item.title}</p> : null}
      {item.mode === "new" && item.description ? <ItemDescription item={item} /> : null}
      {item.mode === "existing" && item.href ? (
        <a className="workflow-start__link" href={item.href}>Open the Work item</a>
      ) : null}
    </div>
  );
}

export function WorkflowStartLists({ view, progress }: { view: WorkflowStartView; progress: Started | Failed | null }) {
  return (
    <>
      {view.jiraLabel && !progress?.jiraKey && !progress?.jiraProblem ? (
        <p className="workflow-start__jira" data-testid="workflow-start-jira">{view.jiraLabel}</p>
      ) : null}

      {view.steps.length ? (
        <ol className="workflow-start__steps" aria-label="Steps">
          {view.steps.map((step, index) => (
            <li key={`${index}-${step}`}>{step}</li>
          ))}
        </ol>
      ) : null}

      {view.notes.length ? (
        <ul className="workflow-start__notes">
          {view.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </>
  );
}

type ChoicesProps = {
  view: WorkflowStartView;
  state: WorkflowStartCardState;
  actionable: boolean;
  locked: boolean;
  failed: Failed | null;
};

export function WorkflowStartChoices({ view, state, actionable, locked, failed }: ChoicesProps) {
  const { runOn, setRunOn, setModel, setModelError, setCost, setCostError } = state;
  return (
    <>
      {view.repository ? (
        <StartRepository
          repository={view.repository}
          value={state.repository}
          onChange={(id) => {
            state.setRepository(id);
            state.setProblem(null);
          }}
          editable={actionable}
          disabled={locked}
          problem={state.problem}
        />
      ) : null}

      {actionable ? (
        <RunOnSelect
          id={state.runOnId}
          options={view.runOn.options}
          value={runOn}
          onChange={setRunOn}
          help={runOnHelp(view.runOn, runOn)}
          disabled={locked}
        />
      ) : null}
      {actionable && view.runOn.options.length ? (
        <StartModelBudget
          projectId={view.projectId ?? ""}
          runOn={runOn}
          model={state.model}
          onModel={(next) => { setModel(next); setModelError(null); }}
          modelError={state.modelError}
          itemId={view.item.id || failed?.itemId || null}
          cost={state.cost}
          onCost={(next) => { setCost(next); setCostError(null); }}
          costError={state.costError}
          disabled={locked}
        />
      ) : null}
    </>
  );
}

type OutcomeProps = {
  view: WorkflowStartView;
  started: Started | null;
  failed: Failed | null;
  problem: string | null;
  skipped: boolean;
  decided: "apply" | "skip" | null;
};

export function WorkflowStartOutcomeLines({ view, started, failed, problem, skipped, decided }: OutcomeProps) {
  const progress = started ?? failed;
  return (
    <>
      {failed ? (
        <p className="workflow-start__problem" role="alert">
          {`${view.workflowTitle} did not start: ${failed.reason}`}
        </p>
      ) : null}

      {started ? (
        <p className="workflow-start__done">
          <a className="ds-btn ds-btn--sm ds-btn--primary" href={started.href} data-testid="workflow-start-open-run">
            {startedLinkLabel(started)}
          </a>
        </p>
      ) : null}
      {progress?.jiraProblem ? (
        <p className="workflow-start__quiet" data-testid="workflow-start-jira-problem">{jiraProblemText(progress.jiraProblem)}</p>
      ) : null}
      {problem && !view.repository ? (
        <p className="workflow-start__problem" role="alert">{problem}</p>
      ) : null}
      {skipped ? <p className="workflow-start__quiet">Not started.</p> : null}
      {decided === "apply" && !started && !failed ? <p className="workflow-start__quiet">Starting…</p> : null}
    </>
  );
}

type ActionsProps = {
  outcome: WorkflowStartOutcome;
  busy: "start" | "skip" | null;
  locked: boolean;
  blocked: string | null;
  otherOpen: boolean;
  onOther: (() => void) | null;
  onRun: (kind: "start" | "skip") => void;
};

export function WorkflowStartActions({ outcome, busy, locked, blocked, otherOpen, onOther, onRun }: ActionsProps) {
  return (
    <div className="workflow-start__actions" role="group" aria-label="Start decision">
      <button
        type="button"
        className="ds-btn ds-btn--sm ds-btn--ghost"
        data-decision-value="skip"
        disabled={locked}
        onClick={() => onRun("skip")}
      >
        {busy === "skip" ? "Sending…" : "Don't start"}
      </button>
      {onOther ? (
        <button
          type="button"
          className="ds-btn ds-btn--sm"
          data-decision-value="other"
          aria-expanded={otherOpen}
          disabled={locked}
          onClick={onOther}
        >
          Other workflow…
        </button>
      ) : null}
      <button
        type="button"
        className="ds-btn ds-btn--sm ds-btn--primary"
        data-decision-value="apply"
        disabled={locked || Boolean(blocked)}
        title={blocked ?? undefined}
        onClick={() => onRun("start")}
      >
        {busy === "start" ? "Starting…" : startButtonLabel(outcome)}
      </button>
      {blocked ? <span className="workflow-start__hint" data-testid="workflow-start-blocked">{blocked}</span> : null}
    </div>
  );
}
