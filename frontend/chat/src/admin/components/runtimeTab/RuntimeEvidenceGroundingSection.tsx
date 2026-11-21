import { useEffect, useState } from "react";

import "../governedWrite/governedWrite.css";
import "./runtimeSections.css";
import { GovernedIssueList } from "../governedWrite/GovernedIssueList";
import { governedRequest, type GovernedIssue } from "../governedWrite/governedRequest";
import {
  EVIDENCE_GROUNDING_PATH,
  agentTypesFromDraft,
  evidenceGroundingPatch,
  parseEvidenceGroundingSettings,
  type EvidenceGroundingSettings,
} from "./evidenceGroundingSettings";

// "document_updater" → "Document updater": an agent type in words; the stored key stays what is saved.
function agentTypeWords(key: string): string {
  const words = key.replace(/[_-]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : key;
}

// The setting's state: loaded once, saved (or reset with null) through the governed request.
function useEvidenceGrounding() {
  const [settings, setSettings] = useState<EvidenceGroundingSettings | null>(null);
  const [draft, setDraft] = useState("");
  const [issues, setIssues] = useState<GovernedIssue[]>([]);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const apply = (payload: unknown) => {
    const parsed = parseEvidenceGroundingSettings(payload);
    setSettings(parsed);
    setDraft(parsed.highRiskAgentTypes.join("\n"));
  };

  useEffect(() => {
    let cancelled = false;
    void governedRequest<unknown>(EVIDENCE_GROUNDING_PATH, { method: "GET" }).then((outcome) => {
      if (cancelled) return;
      if (!outcome.ok) {
        setIssues(outcome.issues);
        return;
      }
      apply(outcome.data);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const save = async (agentTypes: string[] | null) => {
    setSaving(true);
    setIssues([]);
    setNotice(null);
    const outcome = await governedRequest<unknown>(EVIDENCE_GROUNDING_PATH, {
      method: "PUT",
      body: evidenceGroundingPatch(agentTypes),
    });
    setSaving(false);
    if (!outcome.ok) {
      setIssues(outcome.issues);
      return;
    }
    apply(outcome.data);
    setNotice(agentTypes === null ? "Reset to the default list." : "High-risk agent types saved.");
  };

  return { settings, draft, setDraft, issues, saving, notice, save };
}

// Global evidence-grounding setting: the agent types whose turns always obey the
// evidence-grounded answer contract.
export function RuntimeEvidenceGroundingSection() {
  const { settings, draft, setDraft, issues, saving, notice, save } = useEvidenceGrounding();

  return (
    <div className="admin-panel__subsection runtime-panel__card" aria-label="Evidence grounding">
      <div className="admin-panel__section-header">
        <span>Evidence grounding</span>
      </div>
      {/* Which list applies, in words, and the default agent types as words (not their keys). */}
      <p className="admin-panel__hint">
        <strong data-testid="evidence-grounding-source">
          {settings === null ? "Loading…" : settings.source === "configured" ? "A saved list applies" : "The default list applies"}
        </strong>
        {settings ? <> · default: {settings.defaultAgentTypes.map(agentTypeWords).join(", ")}</> : null}
      </p>
      <label className="admin-panel__field">
        <span>High-risk agent types (one per line)</span>
        <textarea
          rows={5}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          disabled={settings === null || saving}
          aria-label="High-risk agent types"
        />
      </label>
      <div className="admin-panel__form-actions">
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={() => void save(agentTypesFromDraft(draft))}
          disabled={settings === null || saving}
        >
          {saving ? "Saving..." : "Save agent types"}
        </button>
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={() => void save(null)}
          disabled={settings === null || saving || settings.source === "default"}
        >
          Reset to the default list
        </button>
      </div>
      <GovernedIssueList issues={issues} label="Evidence grounding errors" />
      {notice ? <p className="governed-notice">{notice}</p> : null}
    </div>
  );
}
