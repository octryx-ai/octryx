import { lazy, Suspense, useState, type Dispatch, type SetStateAction } from "react";

import { StatusLabel, type StatusTone } from "../../layout/StatusLabel";
import {
  answeredCount,
  composeAnswer,
  decisionLabel,
  EMPTY_ANSWERS,
  findingPlace,
  runScreenUrl,
  runScreensPath,
  screensView,
  type DecisionAnswers,
  type DecisionCard as Card,
  type RunScreen,
} from "./decisionCardModel";
import { autoRevisedText, type RunEvent } from "./runHistoryModel";
import { TaskList } from "./TaskList";
import { taskProgress } from "./taskListModel";
import { useRunResource } from "./useRunResource";
import { type RunAction, type RunActionValue, type WorkflowRun } from "./workflowRunTypes";

const MarkdownRenderer = lazy(async () => ({ default: (await import("../MarkdownRenderer")).MarkdownRenderer }));

const pageTheme = (): "dark" | "light" =>
  typeof document !== "undefined" && document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";

const SEVERITY_TONES: Record<string, StatusTone> = { high: "problem", medium: "attention", low: "neutral" };

type DecisionCardProps = {
  run: WorkflowRun;
  card: Card;
  // The run's events (for "revised on its own"); null while they load.
  events?: RunEvent[] | null;
  busy: boolean;
  onChoose: (action: RunAction, value?: RunActionValue) => void;
};
type SetAnswer = (kind: "findings" | "questions", index: number, text: string) => void;

function renderDecisionButtons(
  card: Card,
  { confirm, change }: { confirm: RunAction | null; change: RunAction | null },
  { busy, composed, changeFirst, onChoose }: Pick<DecisionCardProps, "busy" | "onChoose"> & { composed: string; changeFirst: boolean },
) {
  const changeButton = change ? (
    <button
      type="button"
      key="change"
      className={`work-area__button${changeFirst ? " work-area__button--primary" : ""}`}
      disabled={busy || !composed}
      data-testid="decision-card-change"
      onClick={() => onChoose(change, composed)}
    >
      {decisionLabel(card, change)}
    </button>
  ) : null;
  const confirmButton = confirm ? (
    <button
      type="button"
      key="confirm"
      className={`work-area__button${changeFirst ? "" : " work-area__button--primary"}`}
      disabled={busy}
      data-testid="decision-card-confirm"
      onClick={() => onChoose(confirm)}
    >
      {decisionLabel(card, confirm)}
    </button>
  ) : null;
  return changeFirst ? [confirmButton, changeButton] : [changeButton, confirmButton];
}

function DecisionCardHead({ card, revisedAlone }: { card: Card; revisedAlone: string }) {
  return (
  <header className="decision-card__head">
    <div>
      <h3 className="decision-card__title">{card.heading}</h3>
      {card.summary ? <p className="decision-card__summary">{card.summary}</p> : null}
      {revisedAlone ? (
        <p className="decision-card__summary" data-testid="decision-card-auto-revised">{revisedAlone}</p>
      ) : null}
    </div>
    {card.subject === "decisions" && card.verdict === "changes" ? (
      <StatusLabel label="Not ready to ship" tone="problem" />
    ) : null}
  </header>
  );
}

function DecisionFindings({ card, change, answers, set }: {
  card: Card;
  change: RunAction | null;
  answers: DecisionAnswers;
  set: SetAnswer;
}) {
  return (
    <div className="decision-card__group">
      <h4 className="decision-card__label">Findings</h4>
      {card.findings.map((finding, index) => (
        <div className="decision-card__item" key={`${finding.file}:${finding.line}:${index}`}>
          <div className="decision-card__item-head">
            <StatusLabel label={finding.severity || "finding"} tone={SEVERITY_TONES[finding.severity] ?? "neutral"} />
            <span className="decision-card__item-text">{finding.fix}</span>
            <code className="decision-card__place" title={finding.file}>{findingPlace(finding)}</code>
          </div>
          {change ? (
            <label className="decision-card__field">
              <span>Your answer (optional; empty: fixed as proposed)</span>
              <textarea
                className="admin-panel__input"
                rows={2}
                value={answers.findings[index] ?? ""}
                onChange={(event) => set("findings", index, event.target.value)}
              />
            </label>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function DecisionScreens({ runId, shots, onShowAll }: {
  runId: string;
  shots: NonNullable<ReturnType<typeof screensView>>;
  onShowAll: () => void;
}) {
  return (
    <div className="decision-card__group" data-testid="decision-card-screens">
      <div className="decision-card__screens-head">
        <h4 className="decision-card__label">{shots.heading}</h4>
        {shots.more ? (
          <button type="button" className="decision-card__link" onClick={onShowAll}>
            {shots.more}
          </button>
        ) : null}
      </div>
      <div className="decision-card__screens">
        {shots.shown.map((screen) => (
          <figure className="decision-card__screen" key={screen.name}>
            <a
              href={runScreenUrl(runId, screen.name)}
              target="_blank"
              rel="noreferrer"
              aria-label={`Open screenshot ${screen.name}`}
            >
              <img src={runScreenUrl(runId, screen.name)} alt={screen.name} loading="lazy" />
            </a>
            <figcaption>{screen.name}</figcaption>
          </figure>
        ))}
      </div>
      <p className="decision-card__hint decision-card__hint--block">
        Only screenshots from this round's last system test run. Click one to open it full size.
      </p>
    </div>
  );
}

function DecisionQuestions({ card, answers, set }: { card: Card; answers: DecisionAnswers; set: SetAnswer }) {
  return (
    <div className="decision-card__group">
      <h4 className="decision-card__label">{card.subject === "decisions" ? "Assumptions to confirm" : "Open questions"}</h4>
      {card.questions.map((question, index) => (
        <label className="decision-card__field" key={question}>
          <span className="decision-card__question">{index + 1} · {question}</span>
          <input
            className="admin-panel__input"
            type="text"
            value={answers.questions[index] ?? ""}
            onChange={(event) => set("questions", index, event.target.value)}
          />
        </label>
      ))}
    </div>
  );
}

function DecisionOtherAnswer({ card, answers, setAnswers }: {
  card: Card;
  answers: DecisionAnswers;
  setAnswers: Dispatch<SetStateAction<DecisionAnswers>>;
}) {
  return (
      <label className="decision-card__field">
        <span>{card.questions.length || card.findings.length ? "Anything else for the agent" : "Your answer for the agent"}</span>
        <textarea
          className="admin-panel__input"
          rows={2}
          value={answers.other}
          onChange={(event) => setAnswers((current) => ({ ...current, other: event.target.value }))}
        />
      </label>
  );
}

function AgentNote({ note }: { note: string }) {
  return (
    <details className="decision-card__note">
      <summary>The agent's full note</summary>
      <Suspense fallback={<p className="workflow-run-banner__text">{note}</p>}>
        <MarkdownRenderer content={note} theme={pageTheme()} />
      </Suspense>
    </details>
  );
}

// A product owner's decision as one card: the verdict is the heading, every finding and every
// open question has its own answer field, and the primary button follows the verdict. Stop stays in the ⋯ menu.
export function DecisionCard({ run, card, events, busy, onChoose }: DecisionCardProps) {
  const [answers, setAnswers] = useState<DecisionAnswers>(EMPTY_ANSWERS);
  const [allScreens, setAllScreens] = useState(false);
  const isReview = card.subject === "decisions";
  const screens = useRunResource<{ screens: RunScreen[] }>(isReview ? runScreensPath(run.id) : null, run.updated_at);
  const shots = isReview ? screensView(screens?.screens, allScreens) : null;
  const revisedAlone = isReview ? autoRevisedText(events) : "";
  const confirm = run.actions.find((action) => action.key === "confirm") ?? null;
  const change = run.actions.find((action) => action.key === "change") ?? null;
  const composed = composeAnswer(card, answers);
  const answered = answeredCount(card, answers);
  const changeFirst = card.subject === "decisions" ? card.verdict === "changes" : composed.length > 0;
  const gatePassed = run.gate?.state === "passed";

  function set(kind: "findings" | "questions", index: number, text: string) {
    setAnswers((current) => ({ ...current, [kind]: { ...current[kind], [index]: text } }));
  }

  return (
    <section className="decision-card" aria-label={card.heading} data-testid="decision-card">
      <DecisionCardHead card={card} revisedAlone={revisedAlone} />

      {card.subject === "decisions" ? (
        <p className="decision-card__facts">
          {gatePassed ? <span>Checks passed</span> : null}
          {run.branch ? <span>Branch {run.branch}</span> : null}
        </p>
      ) : null}
      {card.findings.length ? <DecisionFindings card={card} change={change} answers={answers} set={set} /> : null}

      {shots ? <DecisionScreens runId={run.id} shots={shots} onShowAll={() => setAllScreens(true)} /> : null}

      {run.task_list?.length ? (
        <div className="decision-card__group" data-testid="decision-card-tasks">
          <h4 className="decision-card__label">Tasks · {taskProgress(run.task_list)}</h4>
          <TaskList items={run.task_list} />
        </div>
      ) : null}
      {card.questions.length ? <DecisionQuestions card={card} answers={answers} set={set} /> : null}

      {change ? <DecisionOtherAnswer card={card} answers={answers} setAnswers={setAnswers} /> : null}
      {card.note ? <AgentNote note={card.note} /> : null}

      <footer className="decision-card__foot">
        <span className="decision-card__hint">
          {card.questions.length ? `${answered} of ${card.questions.length} answered` : ""}
        </span>
        {renderDecisionButtons(card, { confirm, change }, { busy, composed, changeFirst, onChoose })}
      </footer>
    </section>
  );
}
