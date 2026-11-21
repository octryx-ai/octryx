import { useEffect, useState } from "react";

import type { AdminProjectQuality } from "../../types/projectQualityTypes";
import "../governedWrite/governedWrite.css";
import { GovernedIssueList } from "../governedWrite/GovernedIssueList";
import { governedRequest, type GovernedIssue, type GovernedOutcome } from "../governedWrite/governedRequest";
import {
  EVIDENCE_GROUNDING_POLICY_STATES,
  evidenceGroundingPolicyPatch,
  evidenceGroundingPolicyState,
  type EvidenceGroundingPolicyState,
} from "./evidenceGroundingPolicy";

type Props = {
  ctx: Record<string, unknown>;
};

type ProjectConfigPayload = { config?: Record<string, unknown> };

type Outcome = GovernedOutcome<ProjectConfigPayload>;

// A config read or write: its issues, or the stored state (which also becomes the choice). True when it succeeded.
function applyOutcome(outcome: Outcome, set: {
  setStored: (state: EvidenceGroundingPolicyState) => void;
  setChoice: (state: EvidenceGroundingPolicyState) => void;
  setIssues: (issues: GovernedIssue[]) => void;
}): boolean {
  if (!outcome.ok) {
    set.setIssues(outcome.issues);
    return false;
  }
  const state = evidenceGroundingPolicyState(outcome.data.config);
  set.setStored(state);
  set.setChoice(state);
  return true;
}

function GroundingHeader({ stored, saving, unchanged, onSave }: {
  stored: EvidenceGroundingPolicyState | null;
  saving: boolean;
  unchanged: boolean;
  onSave: () => void;
}) {
  return (
    <div className="admin-panel__section-header">
      <div>
        <span>Evidence grounding</span>
        <p className="admin-panel__hint">
          Saved:{" "}
          <strong data-testid="evidence-grounding-stored">{stored ?? "loading"}</strong>
        </p>
      </div>
      <button
        type="button"
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        onClick={onSave}
        disabled={saving || stored === null || unchanged}
      >
        {saving ? "Saving..." : "Save grounding policy"}
      </button>
    </div>
  );
}

function GroundingChoices({ choice, disabled, onChoice }: {
  choice: EvidenceGroundingPolicyState;
  disabled: boolean;
  onChoice: (state: EvidenceGroundingPolicyState) => void;
}) {
  return (
    <div className="governed-choices" role="radiogroup" aria-label="Evidence grounding policy">
      {EVIDENCE_GROUNDING_POLICY_STATES.map((entry) => (
        <label
          key={entry.state}
          className={`governed-choice${choice === entry.state ? " governed-choice--selected" : ""}`}
        >
          <input
            type="radio"
            name="evidence-grounding-policy"
            value={entry.state}
            checked={choice === entry.state}
            onChange={() => onChoice(entry.state)}
            disabled={disabled}
          />
          <span className="governed-choice__key">
            {entry.label} <code>{entry.stored}</code>
          </span>
          <span className="governed-choice__text">{entry.description}</span>
        </label>
      ))}
    </div>
  );
}

// Workspace setting for the evidence-grounded answer contract. Admin-only, validated and
// audited by the project config write (`admin.project_config.updated`).
export function ProjectEvidenceGroundingSection({ ctx }: Props) {
  const project = (ctx as { configuringProjectQuality?: AdminProjectQuality | null })
    .configuringProjectQuality;
  const projectId = project?.id ?? "";
  const configUrl = `/admin/chat/api/panel/projects/${encodeURIComponent(projectId)}/config`;
  const [stored, setStored] = useState<EvidenceGroundingPolicyState | null>(null);
  const [choice, setChoice] = useState<EvidenceGroundingPolicyState>("default");
  const [issues, setIssues] = useState<GovernedIssue[]>([]);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    setStored(null);
    setIssues([]);
    setNotice(null);
    void governedRequest<ProjectConfigPayload>(configUrl, { method: "GET" }).then((outcome) => {
      if (cancelled) return;
      applyOutcome(outcome, { setStored, setChoice, setIssues });
    });
    return () => {
      cancelled = true;
    };
  }, [projectId, configUrl]);

  if (!project) return null;

  const save = async () => {
    setSaving(true);
    setIssues([]);
    setNotice(null);
    const outcome = await governedRequest<ProjectConfigPayload>(configUrl, {
      method: "PUT",
      body: evidenceGroundingPolicyPatch(choice),
    });
    setSaving(false);
    if (applyOutcome(outcome, { setStored, setChoice, setIssues })) setNotice("Evidence grounding policy saved.");
  };

  return (
    <section className="admin-panel__stack" aria-label="Evidence grounding">
      <GroundingHeader stored={stored} saving={saving} unchanged={choice === stored} onSave={() => void save()} />
      <section className="admin-panel__card">
        <p className="admin-panel__hint">
          When turns in this Workspace must answer from retrieved evidence with its source.
        </p>
        <GroundingChoices choice={choice} disabled={stored === null} onChoice={setChoice} />
        <GovernedIssueList issues={issues} label="Evidence grounding errors" />
        {notice ? <p className="governed-notice">{notice}</p> : null}
      </section>
    </section>
  );
}
