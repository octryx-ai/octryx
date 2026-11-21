import { useState } from "react";

import {
  askReporterRefusalText,
  canSendQuestions,
  readAskReporterAnswer,
  reporterQuestionText,
  type ReporterQuestion,
} from "../../../admin/components/securityControls/securityControlsModel";
import { askReporter } from "./incidentApi";

// The analysis's open questions for the reporter. An automatic analysis only proposes them: a person reads them
// and sends them with an in-place confirmation, which posts one Jira comment that mentions the reporter. The state
// line says what happened (proposed, sent, or why not, in words). Everyone who can read the analysis may send (the
// route has the same check); a refusal is shown in place. A send that did not reach Jira keeps the questions
// proposed and the button active, and says why.
export function ReporterQuestions({ workItemId, analysisId, questions, initial }: {
  workItemId: string; analysisId: string | null; questions: string[]; initial: ReporterQuestion | null;
}) {
  const [question, setQuestion] = useState(initial);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!questions.length) return null;
  const sendable = Boolean(analysisId) && canSendQuestions(question, questions.length);
  const state = reporterQuestionText(question);

  const send = async () => {
    if (!analysisId) return;
    setBusy(true);
    setError(null);
    try {
      const answer = readAskReporterAnswer(await askReporter(workItemId, analysisId));
      setQuestion(answer.question ?? question);
      setError(answer.attempt);
      setConfirming(false);
    } catch (failure) {
      setError(askReporterRefusalText(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="work-analysis__questions" data-testid="analysis-questions">
      <h4 className="work-analysis__heading">Open questions for the reporter</h4>
      <ul className="work-detail__object-list">{questions.map((value) => <li key={value}>{value}</li>)}</ul>
      {state ? <p className="work-detail__empty" data-testid="analysis-questions-state" role="status">{state}</p> : null}
      {sendable && !confirming ? (
        <div className="work-analysis__actions">
          <button type="button" className="work-area__button" data-testid="analysis-questions-send"
            onClick={() => { setError(null); setConfirming(true); }}>
            Send questions to reporter
          </button>
        </div>
      ) : null}
      {sendable && confirming ? (
        <div className="work-analysis__confirm" role="group" aria-label="Confirm the questions" data-testid="analysis-questions-confirm">
          <p className="work-analysis__confirm-text">
            Post {questions.length === 1 ? "this question" : `these ${questions.length} questions`} as one Jira comment that mentions the reporter?
          </p>
          <div className="work-analysis__actions">
            <button type="button" className="work-area__button is-active" disabled={busy} onClick={() => void send()}>
              {busy ? "Sending…" : "Send questions"}
            </button>
            <button type="button" className="work-area__button" disabled={busy} onClick={() => setConfirming(false)}>Cancel</button>
          </div>
        </div>
      ) : null}
      {error ? <p className="work-area__error" role="alert" data-testid="analysis-questions-error">{error}</p> : null}
    </div>
  );
}
