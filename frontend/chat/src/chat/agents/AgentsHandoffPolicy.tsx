import { useEffect, useState } from "react";

import { boardLoadErrorText } from "./agentBoardModel";
import { loadHandoffPolicy, saveHandoffPolicy } from "./handoffPolicyApi";
import {
  policyBody,
  policyExplanation,
  policyProblems,
  policySaveErrorText,
  readHandoffPolicy,
  workStateExplanation,
} from "./handoffPolicyModel";
import type { AllowedRequesters, HandoffPolicy, HandoffPolicyAnswer, HandoffMode, PushMode } from "./handoffPolicyModel";

const MODES: Array<[HandoffMode, string, string]> = [
  ["confirm", "Confirm each handoff", "The receiving person or a Workspace admin confirms every takeover."],
  ["auto", "Hand over automatically", "Octryx confirms a takeover by itself when the rules below hold; otherwise a person confirms."],
];

function useHandoffPolicy(projectId: string) {
  const [answer, setAnswer] = useState<HandoffPolicyAnswer | null>(null);
  const [draft, setDraft] = useState<HandoffPolicy | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let current = true;
    setAnswer(null);
    setProblem(null);
    loadHandoffPolicy(projectId).then((payload) => {
      if (!current) return;
      const read = readHandoffPolicy(payload);
      if (!read) setProblem("The server's answer was not a handoff policy.");
      else { setAnswer(read); setDraft(read.policy); }
    }).catch((error) => {
      if (current) setProblem(boardLoadErrorText(error, "handoff policy"));
    });
    return () => { current = false; };
  }, [projectId]);

  const update = (patch: Partial<HandoffPolicy>) => { setMessage(null); setDraft((previous) => (previous ? { ...previous, ...patch } : previous)); };
  const problems = draft ? policyProblems(draft) : [];
  const changed = Boolean(answer && draft && JSON.stringify(policyBody(answer.policy)) !== JSON.stringify(policyBody(draft)));

  const save = async () => {
    if (!draft || problems.length) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await saveHandoffPolicy(projectId, policyBody(draft));
      const read = result.ok ? readHandoffPolicy(result.body) : null;
      if (read) {
        setAnswer(read);
        setDraft(read.policy);
        setMessage({ ok: true, text: "Saved. The handoff policy applies to the next takeover request." });
      } else {
        setMessage({ ok: false, text: result.ok ? "Not saved: the server's answer was not a handoff policy." : policySaveErrorText(result.status, result.body) });
      }
    } catch {
      setMessage({ ok: false, text: "Not saved: the request did not reach the server." });
    } finally {
      setBusy(false);
    }
  };
  return { answer, draft, setDraft, problem, message, setMessage, busy, update, problems, changed, save };
}

type Update = (patch: Partial<HandoffPolicy>) => void;

function NumberField({ label, ariaLabel, min, max, value, onChange }: {
  label: string; ariaLabel: string; min: number; max: number; value: number; onChange: (value: number) => void;
}) {
  return (
    <label className="admin-panel__field"><span>{label}</span>
      <input type="number" min={min} max={max} step={1} value={value} aria-label={ariaLabel}
        onChange={(event) => onChange(Number(event.target.value))} />
    </label>
  );
}

function AutoModeFields({ shown, update }: { shown: HandoffPolicy; update: Update }) {
  return (
    <>
      <NumberField label="Holder threshold (% of weekly allowance)" ariaLabel="Holder threshold" min={1} max={100}
        value={shown.autoThresholdPct} onChange={(value) => update({ autoThresholdPct: value })} />
      <NumberField label="Required spare allowance of the requester (%)" ariaLabel="Required spare allowance" min={0} max={99}
        value={shown.requireSparePct} onChange={(value) => update({ requireSparePct: value })} />
      {shown.offerTimeoutMinutes !== null ? (
        <NumberField label="Offer moves to the next agent after (minutes)" ariaLabel="Offer moves on after" min={1} max={1440}
          value={shown.offerTimeoutMinutes} onChange={(value) => update({ offerTimeoutMinutes: value })} />
      ) : null}
      <label className="admin-panel__field"><span>Who may receive automatically</span>
        <select value={shown.allowedRequesters} aria-label="Allowed requesters"
          onChange={(event) => update({ allowedRequesters: event.target.value as AllowedRequesters })}>
          <option value="members">Any Workspace member's agent</option>
          <option value="admins_and_owners">Only agents of admins and owners</option>
        </select>
      </label>
    </>
  );
}

function PolicyGrid({ shown, update }: { shown: HandoffPolicy; update: Update }) {
  return (
    <div className="agents-handoff-policy__grid">
      {shown.mode === "auto" ? <AutoModeFields shown={shown} update={update} /> : null}
      {shown.autoTriggerPct !== null ? (
        <NumberField label="Hand over by itself at (% of the allowance or daily budget)" ariaLabel="Automatic handoff trigger" min={1}
          max={100} value={shown.autoTriggerPct} onChange={(value) => update({ autoTriggerPct: value })} />
      ) : null}
      {shown.push !== null ? (
        <label className="admin-panel__field"><span>Work in progress travels as</span>
          <select value={shown.push} aria-label="Work in progress travels as"
            onChange={(event) => update({ push: event.target.value as PushMode })}>
            <option value="branch">A branch on the registered repository (bundle if the push fails)</option>
            <option value="bundle_only">A bundle on Octryx only</option>
            <option value="off">Nothing: it stays on the machine</option>
          </select>
        </label>
      ) : null}
    </div>
  );
}

function PolicyFields({ projectId, shown, disabled, update }: { projectId: string; shown: HandoffPolicy; disabled: boolean; update: Update }) {
  return (
    <fieldset className="agents-handoff-policy__fields" disabled={disabled}>
      <legend className="agents-handoff-policy__legend">Mode</legend>
      <div className="agents-choice-cards" role="radiogroup" aria-label="Handoff mode">
        {MODES.map(([mode, label, help]) => (
          <label key={mode} className="admin-option-card">
            <input type="radio" name={`handoff-mode-${projectId}`} value={mode} checked={shown.mode === mode}
              onChange={() => update({ mode })} />
            <span className="admin-option-card__body">
              <span className="admin-option-card__title">{label}</span>
              <span className="admin-option-card__desc">{help}</span>
            </span>
          </label>
        ))}
      </div>
      <PolicyGrid shown={shown} update={update} />
    </fieldset>
  );
}

function PolicyBody({ projectId, answer, shown, policy }: {
  projectId: string; answer: HandoffPolicyAnswer; shown: HandoffPolicy; policy: ReturnType<typeof useHandoffPolicy>;
}) {
  const { busy, problems, changed, message, update, setDraft, setMessage, save } = policy;
  return (
    <>
      <p className="agents-area__hint" data-testid="agents-handoff-policy-source">
        {answer.source === "default" ? "This Workspace uses the default policy." : "This Workspace has its own policy."}
        {answer.canEdit ? "" : " Read-only: Workspace admins and owners can change it."}
      </p>
      <PolicyFields projectId={projectId} shown={shown} disabled={!answer.canEdit || busy} update={update} />
      <div className="agents-area__hint" data-testid="agents-handoff-policy-explanation">
        {[...policyExplanation(shown), ...workStateExplanation(shown)].map((line) => <p key={line} className="agents-handoff-policy__line">{line}</p>)}
      </div>
      {problems.map((entry) => <p key={entry} className="work-area__error" role="alert">{entry}</p>)}
      {answer.canEdit ? (
        <div className="agents-board__actions agents-board__actions--end">
          {changed ? (
            <button type="button" className="admin-panel__action-btn" disabled={busy}
              onClick={() => { setDraft(answer.policy); setMessage(null); }}>Discard changes</button>
          ) : null}
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy || !changed || problems.length > 0}
            onClick={() => void save()}>{busy ? "Saving…" : "Save handoff policy"}</button>
        </div>
      ) : null}
      {message ? (
        <p className={message.ok ? "agents-area__hint" : "work-area__error"} role={message.ok ? "status" : "alert"}
          data-testid="agents-handoff-policy-message">{message.text}</p>
      ) : null}
    </>
  );
}

// "Automatic handoff" in Agents → Claims and handoffs (root freeze 3b): the Workspace's handoff mode. Members
// read it; Workspace admins/owners and platform admins (the server's `can_edit`) change it. The plain-language
// explanation is built from the values, so it always says what the server will do.
export function AgentsHandoffPolicy({ projectId }: { projectId: string }) {
  const policy = useHandoffPolicy(projectId);
  const { answer, draft, problem } = policy;
  const shown = draft ?? answer?.policy ?? null;
  return (
    <section className="admin-panel__card agents-board" aria-label="Automatic handoff" data-testid="agents-handoff-policy">
      <div className="admin-panel__section-header"><h2 className="agents-area__section-title">Automatic handoff</h2></div>
      {problem ? <p className="work-area__error" role="alert" data-testid="agents-handoff-policy-error">{problem}</p>
        : !answer || !shown ? <p className="agents-area__hint" role="status">Loading the handoff policy…</p>
          : <PolicyBody projectId={projectId} answer={answer} shown={shown} policy={policy} />}
    </section>
  );
}
