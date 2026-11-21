import { useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";

import { createCodingReviewEvent } from "../work/workCodingApi";
import type { WorkChangePlan } from "../work/workChangePlanTypes";
import type { WorkChangeUnit } from "../work/workPullRequestTypes";
import type { WorkCodingReviewEvent } from "../work/workCodingReviewTypes";
import {
  REVIEW_DECISION_OPTIONS,
  buildReviewDecisionPayload,
  decisionLabel,
  decisionsForPlan,
  reviewDecisionSubjects,
  type ReviewDecision,
  type ReviewDecisionPayload,
} from "./codingReviewDecisionModel";

type SubmitDecision = (workItemId: string, payload: ReviewDecisionPayload) => Promise<WorkCodingReviewEvent>;

const submitWithApi: SubmitDecision = (workItemId, payload) => createCodingReviewEvent(workItemId, payload);
type Subject = ReturnType<typeof reviewDecisionSubjects>[number];
type Shown = { workItemId: string; planId: string | null };

// Records the decision once; only the same item and plan, still on screen, show its result or error.
async function recordReviewDecision(ctx: {
  payload: ReviewDecisionPayload | null;
  inFlight: MutableRefObject<boolean>;
  mounted: MutableRefObject<boolean>;
  shown: MutableRefObject<Shown>;
  workItemId: string;
  submit: SubmitDecision;
  onRecorded: (event: WorkCodingReviewEvent) => void;
  setSaving: (saving: boolean) => void;
  setError: (error: string | null) => void;
  setDecision: (decision: ReviewDecision | "") => void;
  setNote: (note: string) => void;
}) {
  const { payload, inFlight, mounted, shown, workItemId, submit, onRecorded, setSaving, setError, setDecision, setNote } = ctx;
  if (!payload || inFlight.current) return;
  inFlight.current = true;
  const requestedFor = { ...shown.current };
  setSaving(true);
  setError(null);
  // Only the same item and plan, still on screen, may show this request's result or error.
  const stillShown = () =>
    mounted.current
    && shown.current.workItemId === requestedFor.workItemId
    && shown.current.planId === requestedFor.planId;
  try {
    const created = await submit(workItemId, payload);
    if (!stillShown()) return;
    onRecorded(created);
    setDecision("");
    setNote("");
  } catch (caught) {
    // The inputs stay, so the reviewer can reload the plan or retry without retyping.
    if (stillShown()) {
      const message = caught && typeof caught === "object" && "message" in caught ? (caught as { message?: unknown }).message : null;
      setError(typeof message === "string" && message ? message : "The review decision could not be saved.");
    }
  } finally {
    inFlight.current = false;
    if (mounted.current) setSaving(false);
  }
}

function DecisionHeading({ latestPlan }: { latestPlan: WorkChangePlan | null }) {
  return (
    <>
      <div className="coding-review__section-heading">
        <span>Review decision</span>
        <strong>{latestPlan ? `plan v${latestPlan.version} · ${latestPlan.status.replaceAll("_", " ")}` : "no plan"}</strong>
      </div>
      {latestPlan ? null : <p>No Change Plan is attached, so there is nothing to review yet.</p>}
    </>
  );
}

type DecisionFormProps = {
  latestPlan: WorkChangePlan | null;
  subjects: Subject[];
  subjectValue: string;
  setSubjectValue: (value: string) => void;
  decision: ReviewDecision | "";
  setDecision: (decision: ReviewDecision | "") => void;
  note: string;
  setNote: (note: string) => void;
  saving: boolean;
  subject: Subject | null;
  error: string | null;
  canRecord: boolean;
  recordDecision: () => Promise<void>;
  recorded: ReturnType<typeof decisionsForPlan>;
};

// The form: heading, subject, decision and note, the record button and the decisions recorded for this plan.
function DecisionForm(props: DecisionFormProps) {
  const {
    latestPlan, subjects, subjectValue, setSubjectValue, decision, setDecision, note, setNote, saving, subject, error, canRecord,
    recordDecision, recorded,
  } = props;
  return (
    <section className="coding-review__form" aria-label="Review decision">
      <DecisionHeading latestPlan={latestPlan} />
      <label>
        Subject
        <select
          value={subjectValue}
          disabled={!latestPlan || saving}
          onChange={(event) => setSubjectValue(event.target.value)}
        >
          {subjects.length > 1 ? <option value="">Choose the Change Unit</option> : null}
          {subjects.map((entry) => (
            <option key={entry.value} value={entry.value}>
              {entry.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Decision
        <select
          value={decision}
          disabled={!latestPlan || saving}
          onChange={(event) => setDecision(event.target.value as ReviewDecision | "")}
        >
          <option value="">Choose a decision</option>
          {REVIEW_DECISION_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Note
        <textarea
          value={note}
          disabled={!latestPlan || saving}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Optional: what you reviewed or what must change."
        />
      </label>
      {subject?.changeUnitId && !subject.marker ? (
        <p className="coding-review__error">This Change Unit's state is not loaded; reload before recording a decision.</p>
      ) : null}
      {error ? <p className="coding-review__error" role="alert">{error}</p> : null}
      <button type="button" onClick={() => void recordDecision()} disabled={!canRecord || saving}>
        {saving ? "Recording…" : "Record decision"}
      </button>
      {recorded.length > 0 ? <RecordedDecisions recorded={recorded} subjects={subjects} /> : null}
    </section>
  );
}

function RecordedDecisions({ recorded, subjects }: { recorded: ReturnType<typeof decisionsForPlan>; subjects: Subject[] }) {
  return (
      <ul aria-label="Recorded review decisions">
        {recorded.map((entry) => (
          <li key={entry.id}>
            <strong>{entry.reviewer}</strong> · {decisionLabel(entry.decision)} ·{" "}
            {subjects.find((candidate) => candidate.changeUnitId === entry.changeUnitId)?.label ?? "Earlier subject"}
            {entry.createdAt ? ` · ${entry.createdAt}` : ""}
          </li>
        ))}
      </ul>
  );
}

// The reviewer's inputs, kept until the item, the displayed plan or the available subjects really change, and the
// refs that keep a late answer from reaching another selection.
function useDecisionDraft(
  workItemId: string,
  latestPlan: WorkChangePlan | null,
  subjects: Subject[],
  subjectSignature: string,
) {
  const [subjectValue, setSubjectValue] = useState(subjects.length === 1 ? subjects[0].value : "");
  const [decision, setDecision] = useState<ReviewDecision | "">("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  // The item and plan the panel shows now; a late response for another selection is not applied.
  const shown = useRef({ workItemId, planId: latestPlan?.id ?? null });
  shown.current = { workItemId, planId: latestPlan?.id ?? null };

  useEffect(() => {
    setSubjectValue(subjects.length === 1 ? subjects[0].value : "");
    setDecision("");
    setNote("");
    setError(null);
    // Reset only when the item, the displayed plan or the available subjects really change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workItemId, latestPlan?.id, subjectSignature]);

  return {
    subjectValue, setSubjectValue, decision, setDecision, note, setNote, saving, setSaving, error, setError, inFlight, mounted, shown,
  };
}

// Review decision: an explicit Approve / Request changes / Reject for the displayed plan
// version and one whole Change Unit (or the whole Work Item without units). It is separate from file
// feedback, so a file comment never reads as an approval of all changes.
export function CodingReviewDecisionPanel({
  workItemId,
  latestPlan,
  changeUnits,
  events,
  onRecorded,
  submit = submitWithApi,
}: {
  workItemId: string;
  latestPlan: WorkChangePlan | null;
  changeUnits: WorkChangeUnit[];
  events: WorkCodingReviewEvent[];
  onRecorded: (event: WorkCodingReviewEvent) => void;
  submit?: SubmitDecision;
}) {
  const subjects = useMemo(() => reviewDecisionSubjects(changeUnits), [changeUnits]);
  // A stable signature: a new array with the same units must not reset what the reviewer typed.
  const subjectSignature = subjects.map((entry) => entry.value).join("|");
  const {
    subjectValue, setSubjectValue, decision, setDecision, note, setNote, saving, setSaving, error, setError, inFlight, mounted, shown,
  } = useDecisionDraft(workItemId, latestPlan, subjects, subjectSignature);

  const subject = subjects.find((entry) => entry.value === subjectValue) ?? null;
  const payload = buildReviewDecisionPayload({ plan: latestPlan, subject, decision, note });
  const recorded = decisionsForPlan(events, latestPlan?.id ?? null);

  async function recordDecision() {
    await recordReviewDecision({
      payload, inFlight, mounted, shown, workItemId, submit, onRecorded, setSaving, setError, setDecision, setNote,
    });
  }

  return (
    <DecisionForm latestPlan={latestPlan} subjects={subjects} subjectValue={subjectValue} setSubjectValue={setSubjectValue}
      decision={decision} setDecision={setDecision} note={note} setNote={setNote} saving={saving} subject={subject} error={error}
      canRecord={Boolean(payload)} recordDecision={recordDecision} recorded={recorded} />
  );
}
