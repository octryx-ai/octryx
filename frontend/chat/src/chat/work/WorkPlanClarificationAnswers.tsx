import { useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import type { WorkChangePlan } from "./workChangePlanTypes";
import {
  checkClarificationDraft,
  clarificationErrorText,
  isAnswerable,
  retainedClarification,
  type ClarificationAnswer,
} from "./workPlanClarificationModel";
import { formatDateTime } from "./workUtils";

function without<T>(record: Record<string, T>, key: string): Record<string, T> {
  const next = { ...record };
  delete next[key];
  return next;
}

export type ClarificationAnswerResult = { ok: true } | { ok: false; message: string };
type Retained = NonNullable<ReturnType<typeof retainedClarification>>;
type DraftCheck = ReturnType<typeof checkClarificationDraft>;

// The answers a revised version was generated from, with who answered and what stayed open.
function RetainedAnswers({ retained }: { retained: Retained }) {
  return (
    <div className="work-change-plan__delta" data-testid="clarification-retained">
      <strong>Answers from v{retained.sourceVersion}</strong>
      <span>
        {`Answered by ${retained.answeredByLabel || "a recorded user"}`}
        {retained.answeredAt ? ` · ${formatDateTime(retained.answeredAt)}` : ""}.{" "}
        {retained.unanswered.length
          ? `${retained.unanswered.length} question${retained.unanswered.length === 1 ? " was" : "s were"} left unanswered.`
          : "Every question was answered."}
      </span>
      {!retained.answeredByLabel && retained.answeredBy ? <span>Recorded user id: {retained.answeredBy}</span> : null}
      <ul>
        {retained.answers.map((entry) => (
          <li key={entry.question_index}>
            Q{entry.question_index + 1}. {entry.question} — {entry.answer}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ClarificationForm({ plan, draft, check, busy, setAnswer, submit }: {
  plan: WorkChangePlan;
  draft: string[];
  check: DraftCheck;
  busy: boolean;
  setAnswer: (index: number, value: string) => void;
  submit: () => Promise<void>;
}) {
  return (
    <div data-testid="clarification-answers">
      <p>
        Answer what you can. Unanswered questions stay open, and the revised version still needs review
        before execution.
      </p>
      {plan.open_questions.map((question, index) => {
        const value = draft[index] || "";
        const id = `plan-${plan.id}-answer-${index}`;
        const fieldError = check.errors[index];
        return (
          <div key={index} className="work-change-plan__decision">
            <label htmlFor={id}>Q{index + 1}. {question}</label>
            <textarea
              id={id}
              value={value}
              disabled={busy}
              aria-invalid={Boolean(fieldError)}
              onChange={(event) => setAnswer(index, event.target.value)}
              placeholder="Your answer"
            />
            <span>
              {fieldError || (value.trim() ? `${value.trim().length} characters` : "Unanswered")}
            </span>
          </div>
        );
      })}
      {check.totalError ? <p role="alert">{check.totalError}</p> : null}
      <div className="work-change-plan__versions">
        <span>
          {check.answers.length} of {plan.open_questions.length} answered
          {check.unanswered.length ? ` · unanswered: ${check.unanswered.map((index) => `Q${index + 1}`).join(", ")}` : ""}
        </span>
        <button
          type="button"
          className="work-area__button is-active"
          disabled={busy || !check.payload}
          onClick={() => void submit()}
        >
          {busy ? "Working..." : `Generate v${plan.version + 1} from answers`}
        </button>
      </div>
    </div>
  );
}

type AnswerHandler = (
  plan: WorkChangePlan,
  payload: { expected_latest_version: number; answers: ClarificationAnswer[] },
) => Promise<ClarificationAnswerResult>;

async function submitAnswers(ctx: {
  plan: WorkChangePlan;
  drafts: Record<string, string[]>;
  busy: boolean;
  sending: MutableRefObject<boolean>;
  onAnswer: AnswerHandler;
  setErrors: Dispatch<SetStateAction<Record<string, string>>>;
  setDrafts: Dispatch<SetStateAction<Record<string, string[]>>>;
}) {
  const { plan, drafts, busy, sending, onAnswer, setErrors, setDrafts } = ctx;
  // The request is bound to the version shown when it was sent.
  const target = plan;
  const payload = checkClarificationDraft(target, drafts[target.id] || []).payload;
  if (busy || sending.current || !payload) return;
  sending.current = true;
  setErrors((previous) => without(previous, target.id));
  try {
    const result = await onAnswer(target, payload);
    if (result.ok) setDrafts((previous) => without(previous, target.id));
    else setErrors((previous) => ({ ...previous, [target.id]: clarificationErrorText(result.message) }));
  } finally {
    sending.current = false;
  }
}

function ClosedQuestions({ plan, newest }: { plan: WorkChangePlan; newest: WorkChangePlan | null }) {
  return (
    <>
      <ul>
        {plan.open_questions.map((question, index) => <li key={index}>{question}</li>)}
      </ul>
      <p className="work-detail__empty">
        {newest && newest.id !== plan.id
          ? `Only the newest version can be answered (v${newest.version}).`
          : "This version is decided; its questions can no longer be answered."}
      </p>
    </>
  );
}

function UnsentAnswers({ plan, check }: { plan: WorkChangePlan; check: DraftCheck }) {
  return (
    <div className="work-change-plan__delta" data-testid="clarification-unsent">
      <strong>Your unsent answers for v{plan.version} are kept</strong>
      <ul>
        {check.answers.map((entry) => (
          <li key={entry.question_index}>Q{entry.question_index + 1}. {entry.answer}</li>
        ))}
      </ul>
    </div>
  );
}

// The open questions of the selected plan version. The newest open version can be answered
// question by question; the request is bound to that exact version. Answers are kept per version in
// this component while it is mounted: switching versions, a failed request or a version that was
// replaced meanwhile never sends or drops them silently. A revised version shows the answers it was
// generated from.
export function WorkPlanClarificationAnswers({
  plan,
  newest,
  busy,
  onAnswer,
}: {
  plan: WorkChangePlan;
  newest: WorkChangePlan | null;
  busy: boolean;
  onAnswer: AnswerHandler;
}) {
  const [drafts, setDrafts] = useState<Record<string, string[]>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const sending = useRef(false);
  const retained = retainedClarification(plan);
  const answerable = isAnswerable(plan, newest);
  const draft = drafts[plan.id] || [];
  const check = checkClarificationDraft(plan, draft);
  const unsent = !answerable && check.answers.length > 0;

  function setAnswer(index: number, value: string) {
    setDrafts((previous) => {
      const next = [...(previous[plan.id] || [])];
      next[index] = value;
      return { ...previous, [plan.id]: next };
    });
  }

  async function submit() {
    await submitAnswers({ plan, drafts, busy, sending, onAnswer, setErrors, setDrafts });
  }

  return (
    <>
      {retained ? <RetainedAnswers retained={retained} /> : null}

      {plan.open_questions.length === 0 ? <p>No open clarification questions.</p> : null}

      {plan.open_questions.length > 0 && !answerable ? <ClosedQuestions plan={plan} newest={newest} /> : null}

      {unsent ? <UnsentAnswers plan={plan} check={check} /> : null}

      {answerable ? (
        <ClarificationForm plan={plan} draft={draft} check={check} busy={busy} setAnswer={setAnswer} submit={submit} />
      ) : null}

      {errors[plan.id] ? <p className="work-detail__empty" role="alert">{errors[plan.id]}</p> : null}
    </>
  );
}
