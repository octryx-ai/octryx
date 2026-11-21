import { useEffect, useState } from "react";

import { OptionCards } from "../../admin/components/settingsKit/SettingsKit";
import { SaveLine } from "./SaveLine";
import { answerOf, type Question, type StudioPayload } from "./specStudioModel";
import type { SpecStudioHandle } from "./useSpecStudio";

// Questions as choices with the proposal preselected and marked, plus an own answer. Whatever the product owner picks
// lands in SPEC.md as a decision naming the code identifier; some answers change the mock above.

function QuestionCard({ index, question, payload, studio }: { index: number; question: Question; payload: StudioPayload;
  studio: SpecStudioHandle }) {
  const answer = answerOf(question, payload.state);
  const [other, setOther] = useState(answer.other);
  useEffect(() => setOther(answer.other), [answer.other]);
  const key = `other:${question.id}`;
  const sendOther = () => {
    studio.markDirty(key, false);
    const text = other.trim();
    if (text && text !== answer.other) void studio.save("questions", { op: "answer", question: question.id, other: text });
    if (!text && answer.other) void studio.save("questions", { op: "answer", question: question.id, value: question.proposal });
  };
  return (
    <div className="ds-card studio-question">
      <h3 className="ds-card__title">{index}. {question.question}</h3>
      {question.why ? <p className="ds-card__meta">{question.why}</p> : null}
      <OptionCards name={`q-${question.id}`} label={question.question} value={answer.other ? null : answer.value}
        disabled={payload.frozen}
        options={question.options.map((option) => ({ value: option.value, title: option.label, desc: option.detail,
          badge: option.value === question.proposal ? "Proposal" : undefined }))}
        onChange={(value) => { setOther(""); void studio.save("questions", { op: "answer", question: question.id, value }); }} />
      <input type="text" className="admin-panel__input ds-input studio-other" value={other} disabled={payload.frozen}
        placeholder="Something else: your own answer…" aria-label={`Own answer to: ${question.question}`}
        onChange={(event) => { setOther(event.target.value); studio.markDirty(key, event.target.value !== answer.other); }}
        onBlur={sendOther} onKeyDown={(event) => { if (event.key === "Enter") sendOther(); }} />
    </div>
  );
}

export function StudioQuestions({ payload, studio }: { payload: StudioPayload; studio: SpecStudioHandle }) {
  const questions = payload.artefact.questions;
  if (!questions.length) return <p className="studio-hint">The spec phase has no question for you.</p>;
  return (
    <div className="studio-stack">
      {questions.map((question, index) => (
        <QuestionCard key={question.id} index={index + 1} question={question} payload={payload} studio={studio} />
      ))}
      <SaveLine save={studio.saves.questions} />
    </div>
  );
}
