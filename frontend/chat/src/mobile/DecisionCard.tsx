// A product owner's decision on the phone (the web's DecisionCard, same model: decisionCardModel): the verdict as the
// heading, every finding and every open question with its own answer field, and the two choices named by what happens
// next. The answers become the one text the run's change action posts.

import { useState } from "react";
import { StatusLabel, type StatusTone } from "../layout/StatusLabel";
import {
  answeredCount,
  composeAnswer,
  decisionLabel,
  EMPTY_ANSWERS,
  findingPlace,
  type DecisionAnswers,
  type DecisionCard as Card,
} from "../chat/workflowRun/decisionCardModel";
import { taskProgress } from "../chat/workflowRun/taskListModel";
import type { PayloadView } from "../chat/workflowRun/workflowRunPayloadView";
import type { WorkflowRun } from "../chat/workflowRun/workflowRunTypes";
import { RunActionForm } from "./RunActions";
import { RunPayload } from "./RunPayload";

const capitalised = (value: string) => (value ? value[0].toUpperCase() + value.slice(1) : "");
const SEVERITY_TONES: Record<string, StatusTone> = { high: "problem", medium: "attention", low: "neutral" };

type SetAnswer = (kind: "findings" | "questions", index: number, text: string) => void;

function DecisionFindings({ card, canChange, answers, set }: { card: Card; canChange: boolean; answers: DecisionAnswers; set: SetAnswer }) {
  return (
    <div className="m-decision-group">
      <h3 className="m-section">Findings</h3>
      {card.findings.map((finding, index) => (
        <div className="m-finding" key={`${finding.file}:${finding.line}:${index}`}>
          <div className="m-finding-head">
            <StatusLabel label={capitalised(finding.severity) || "Finding"} tone={SEVERITY_TONES[finding.severity] ?? "neutral"} />
            <code title={finding.file}>{findingPlace(finding)}</code>
          </div>
          <p>{finding.fix}</p>
          {canChange && (
            <label className="m-field">
              <span>Your answer (optional; empty: fixed as proposed)</span>
              <textarea
                rows={2}
                value={answers.findings[index] ?? ""}
                onChange={(event) => set("findings", index, event.target.value)}
              />
            </label>
          )}
        </div>
      ))}
    </div>
  );
}

function DecisionQuestions({ card, answers, set }: { card: Card; answers: DecisionAnswers; set: SetAnswer }) {
  return (
    <div className="m-decision-group">
      <h3 className="m-section">{card.subject === "decisions" ? "Assumptions to confirm" : "Open questions"}</h3>
      {card.questions.map((question, index) => (
        <label className="m-field" key={question}>
          <span className="m-question">
            {index + 1}. {question}
          </span>
          <input
            type="text"
            value={answers.questions[index] ?? ""}
            onChange={(event) => set("questions", index, event.target.value)}
          />
        </label>
      ))}
    </div>
  );
}

// The two choices, named by what happens next; the one that fits the answers comes first and is primary.
function decisionButtons(run: WorkflowRun, card: Card, composed: string, changeFirst: boolean, onDone: (run: WorkflowRun) => void) {
  const confirm = run.actions.find((action) => action.key === "confirm") ?? null;
  const change = run.actions.find((action) => action.key === "change") ?? null;
  const changeButton = change && (
    <RunActionForm
      key="change"
      run={run}
      action={change}
      primary={changeFirst}
      label={decisionLabel(card, change)}
      value={composed}
      onDone={onDone}
    />
  );
  const confirmButton = confirm && (
    <RunActionForm
      key="confirm"
      run={run}
      action={confirm}
      primary={!changeFirst}
      label={decisionLabel(card, confirm)}
      value={null}
      onDone={onDone}
    />
  );
  return changeFirst ? [changeButton, confirmButton] : [confirmButton, changeButton];
}

function DecisionHead({ card }: { card: Card }) {
  return (
    <header className="m-decision-head">
      <span className="m-eyebrow">Your decision</span>
      <h2>{card.heading}</h2>
      {card.subject === "decisions" && card.verdict === "changes" && (
        <StatusLabel label="Not ready to ship" tone="problem" />
      )}
      {card.summary && <p>{card.summary}</p>}
    </header>
  );
}

function AgentNote({ note }: { note: string }) {
  return (
    <details className="m-fold">
      <summary>The agent's full note</summary>
      <p className="m-note">{note}</p>
    </details>
  );
}

export function DecisionCard({
  run,
  card,
  payload = null,
  onDone,
}: {
  run: WorkflowRun;
  card: Card;
  // What the run waits on (payloadView): for a spec interview its text is the whole question round.
  payload?: PayloadView | null;
  onDone: (run: WorkflowRun) => void;
}) {
  const [answers, setAnswers] = useState<DecisionAnswers>(EMPTY_ANSWERS);
  const change = run.actions.find((action) => action.key === "change") ?? null;
  const composed = composeAnswer(card, answers);
  const answered = answeredCount(card, answers);
  const changeFirst = card.subject === "decisions" ? card.verdict === "changes" : composed.length > 0;
  const set: SetAnswer = (kind, index, text) =>
    setAnswers((current) => ({ ...current, [kind]: { ...current[kind], [index]: text } }));

  return (
    <section className="m-decision" aria-label={card.heading} data-testid="m-decision-card">
      <DecisionHead card={card} />

      <RunPayload view={payload} showHeading={false} />

      {card.findings.length > 0 && <DecisionFindings card={card} canChange={Boolean(change)} answers={answers} set={set} />}

      {run.task_list?.length ? (
        <p className="m-facts-line">Tasks · {taskProgress(run.task_list)}</p>
      ) : null}

      {card.questions.length > 0 && <DecisionQuestions card={card} answers={answers} set={set} />}

      {change && (
        <label className="m-field">
          <span>{card.questions.length || card.findings.length ? "Anything else for the agent" : "Your answer for the agent"}</span>
          <textarea
            rows={3}
            value={answers.other}
            onChange={(event) => setAnswers((current) => ({ ...current, other: event.target.value }))}
          />
        </label>
      )}

      {card.note && card.note !== payload?.text && <AgentNote note={card.note} />}

      <footer className="m-decision-foot">
        {card.questions.length > 0 && (
          <span className="m-muted">
            {answered} of {card.questions.length} answered
          </span>
        )}
        {decisionButtons(run, card, composed, changeFirst, onDone)}
      </footer>
    </section>
  );
}
