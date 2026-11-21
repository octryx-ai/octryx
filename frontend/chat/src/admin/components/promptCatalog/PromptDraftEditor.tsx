import { useState } from "react";
import { GovernedDrawer } from "../governedRegistry/GovernedDrawer";
import { PromptRefusalBox } from "./PromptRefusalBox";
import { promptCatalogApi } from "./promptCatalogApi";
import { PromptPlaceholderList } from "./PromptPlaceholderList";
import { describePromptRefusal, placeholderPreview, type PromptRefusal, type ScopeRef } from "./promptCatalogModel";
import type { PromptVersion } from "./promptCatalogTypes";

type Props = {
  promptKey: string;
  placeholders: string[];
  placeholderDescriptions?: Record<string, string>;
  literal?: boolean;
  scope: ScopeRef;
  // Display name of the scope ("Payments", "epic-delivery").
  scopeLabel: string;
  initialBody: string;
  onSaved: (version: PromptVersion) => void;
  onClose: () => void;
};

// Write a new draft version at one scope: global, a workflow or a Workspace (versions are append-only, an
// edit never changes a stored body). The closed placeholder set is shown with meanings and checked as you type;
// the server's refusal is final and shown in plain words.
export function PromptDraftEditor({
  promptKey,
  placeholders,
  placeholderDescriptions,
  literal = false,
  scope,
  scopeLabel,
  initialBody,
  onSaved,
  onClose,
}: Props) {
  const [body, setBody] = useState(initialBody);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<PromptRefusal | null>(null);
  // A literal key (tool description) is plain text: braces are never placeholders.
  const preview = literal ? { unknown: [] as string[] } : placeholderPreview(body, placeholders);

  async function save() {
    setBusy(true);
    setRefusal(null);
    try {
      onSaved(await promptCatalogApi.createDraft(promptKey, { ...scope, body, change_note: note }));
    } catch (error) {
      setRefusal(describePromptRefusal(error));
    } finally {
      setBusy(false);
    }
  }

  const footer = (
    <div className="pc-row pc-row--end">
      <button type="button" className="admin-panel__action-btn" onClick={onClose}>
        Cancel
      </button>
      <button
        type="button"
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        disabled={busy || !body.trim() || preview.unknown.length > 0}
        onClick={() => void save()}
      >
        {busy ? "Saving…" : "Save draft"}
      </button>
    </div>
  );

  return (
    <GovernedDrawer variant="gate" eyebrow="New draft version" title={promptKey} onClose={onClose} footer={footer}>
      <PromptRefusalBox refusal={refusal} />
      <span className="ws-muted" data-testid="pc-draft-scope">{scopeSentence(scope, scopeLabel)}</span>
      {literal ? (
        <span className="ws-muted">Served verbatim: braces are plain text, not placeholders.</span>
      ) : (
        <PromptPlaceholderList placeholders={placeholders} descriptions={placeholderDescriptions} />
      )}
      <label className="pc-field">
        <span className="pc-label">Body</span>
        <textarea className="admin-panel__form-input pc-textarea" value={body} onChange={(event) => setBody(event.target.value)} rows={18} />
      </label>
      {preview.unknown.length ? (
        <div className="ws-alert ws-alert--error" role="alert">
          This text uses {preview.unknown.map((name) => `{${name}}`).join(", ")}, which this key does not fill in.
          Remove it or use one of the placeholders listed above.
        </div>
      ) : null}
      <label className="pc-field">
        <span className="pc-label">Change note</span>
        <input className="admin-panel__form-input" maxLength={500} value={note} onChange={(event) => setNote(event.target.value)} />
      </label>
    </GovernedDrawer>
  );
}

// Who gets the text once a second person approved and published it.
function scopeSentence(scope: ScopeRef, label: string): string {
  const review = "After a second person approves and publishes it";
  if (scope.scope_type === "global") return `Global. ${review}, every run without its own workflow or Workspace text uses it.`;
  if (scope.scope_type === "workflow") return `Workflow ${label}. ${review}, every run of this workflow uses it, unless its Workspace has its own text.`;
  return `Workspace ${label}. ${review}, every run in this Workspace uses it.`;
}
