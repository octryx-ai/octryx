import { Suspense } from "react";
import type { ComponentType } from "react";

import type { CedarEditorProps } from "./CedarPolicyEditor";
import { STATE_LABELS } from "./policyEngineStatus";
import { diffSummary } from "./policyEngineVersions";
import type { PolicyIssue, PolicyVersion } from "./policyEngineVersions";
import { PolicyTestReport } from "./PolicyTestReport";
import { cedarSetActions, useCedarSet } from "./useCedarSet";
import type { Message } from "./useCedarSet";

// Back, the working version's state, Validate and Save to draft.
function CedarToolbar({ working, busy, editable, dirty, onBack, onValidate, onSave }: {
  working: PolicyVersion | null;
  busy: boolean;
  editable: boolean;
  dirty: boolean;
  onBack: () => void;
  onValidate: () => void;
  onSave: () => void;
}) {
  return (
    <div className="policies__flex-between">
      <div className="policies__row">
        <button type="button" className="admin-panel__action-btn" data-testid="cedar-back" onClick={onBack}>← Policies</button>
        <span className="admin-panel__title">Hand-written Cedar</span>
        <span className="work-badge work-badge--neutral" data-testid="cedar-working-state">
          {working ? `Version ${working.version}: ${STATE_LABELS[working.state] ?? working.state}` : "No draft"}
        </span>
      </div>
      <div className="policies__row">
        <button type="button" className="admin-panel__action-btn" data-testid="cedar-validate" disabled={busy} onClick={onValidate}>Validate</button>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="cedar-save"
          disabled={busy || !editable || !dirty} onClick={onSave}>Save to draft</button>
      </div>
    </div>
  );
}

// Below the editor: frozen note, the server's issues, the test report, a save conflict and the last message.
function CedarFeedback({ editable, issues, working, conflict, busy, message, onLoadTheirs, onOverwrite }: {
  editable: boolean;
  issues: PolicyIssue[];
  working: PolicyVersion | null;
  conflict: PolicyVersion | null;
  busy: boolean;
  message: Message | null;
  onLoadTheirs: () => void;
  onOverwrite: (digest: string) => void;
}) {
  return (
    <>
    {!editable ? <div className="policies__note">This version is in review: its text is frozen. Withdraw it to edit again.</div> : null}
    {issues.length ? (
      <ul className="workspace-classification__message" role="alert" data-testid="cedar-issues">
        {issues.map((item, index) => (
          <li key={`${item.policyId}-${index}`}>{item.policyId ? `${item.policyId}: ` : ""}{item.message}{item.line ? ` (line ${item.line})` : ""}</li>
        ))}
      </ul>
    ) : null}
    {working?.testReport ? <PolicyTestReport report={working.testReport} /> : null}
    {conflict ? (
      <div className="policies__warn" role="alert" data-testid="cedar-conflict">
        Someone else saved draft v{conflict.version} while you were editing. Your text is still in the editor.
        <div className="policies__row">
          <button type="button" className="admin-panel__action-btn" data-testid="cedar-conflict-load" disabled={busy} onClick={onLoadTheirs}>Load their version (discard mine)</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger" data-testid="cedar-conflict-overwrite" disabled={busy}
            onClick={() => onOverwrite(conflict.digest)}>Save mine over it</button>
        </div>
      </div>
    ) : null}
    {message ? <p className={message.ok ? "admin-panel__success" : "workspace-classification__message"} role={message.ok ? "status" : "alert"} data-testid="cedar-message">{message.text}</p> : null}
    </>
  );
}

// "Advanced · Hand-written Cedar": the whole custom set as Cedar in the dark Monaco editor —
// highlighting, schema completion, live validation, a diff against the published version. The server validates
// every save and runs the saved test cases. Policies the builder cannot express are written here and show as
// "Hand-written" in the list. A save carries the digest the text started from (If-Match); when another admin saved
// the draft meanwhile, the editor keeps this text and asks: load their version, or save this one over it.
export function CedarSetEditor({ editor: EditorComponent, schema, published, working, initialDiff = false, onBack, onChanged }: {
  editor: ComponentType<CedarEditorProps>;
  schema: string;
  published: PolicyVersion | null;
  working: PolicyVersion | null;
  initialDiff?: boolean;
  onBack: () => void;
  onChanged: () => Promise<void>;
}) {
  const state = useCedarSet(published, working, initialDiff);
  const { text, setText, note, setNote, issues, setIssues, live, showDiff, setShowDiff, busy, message, conflict, onLiveIssues } = state;
  const { validate, save, loadTheirs } = cedarSetActions(state, working, onChanged);

  const editable = !working || working.state === "draft";
  const dirty = text !== (working?.policies ?? published?.policies ?? "") || note !== (working?.note ?? "");
  const diff = diffSummary(published?.policies ?? "", text);

  return (
    <div className="policies__pane" data-testid="cedar-policies">
      <CedarToolbar working={working} busy={busy} editable={editable} dirty={dirty} onBack={onBack}
        onValidate={() => void validate()} onSave={() => void save()} />
      <section className="admin-panel__card" aria-label="Custom policies" data-testid="cedar-custom">
        <p className="admin-panel__hint">
          The whole custom policy set as Cedar. Each policy is a <span className="admin-policy-inline-code">forbid</span> with a unique
          <span className="admin-policy-inline-code">@id</span>; it narrows the generated baseline and always wins over it. Published: {published ? `version ${published.version}` : "none"}.
        </p>
        <div className="admin-panel__form-grid">
          <label className="admin-panel__field"><span>Change note</span>
            <input type="text" value={note} maxLength={500} disabled={!editable || busy} data-testid="cedar-note" onChange={(event) => setNote(event.target.value)} /></label>
        </div>
        <label className="policies__row policies__src">
          <input type="checkbox" checked={showDiff} data-testid="cedar-diff-toggle" onChange={(event) => setShowDiff(event.target.checked)} />
          Compare with the published version (+{diff.added} / −{diff.removed} lines)
        </label>
        <Suspense fallback={<p className="admin-panel__hint">Loading the editor…</p>}>
          <EditorComponent value={text} onChange={(next) => { setText(next); setIssues([]); }} readOnly={!editable || busy}
            schema={schema} original={published?.policies ?? ""} showDiff={showDiff} onLiveIssues={onLiveIssues} />
        </Suspense>
        <p className="admin-panel__hint" data-testid="cedar-live">
          {live === null ? "Live validation is not available in this browser; the server validates on save."
            : live.length ? `${live.length} problem${live.length === 1 ? "" : "s"} found while typing.` : "No problem found while typing."}
        </p>
        <CedarFeedback editable={editable} issues={issues} working={working} conflict={conflict} busy={busy} message={message}
          onLoadTheirs={loadTheirs} onOverwrite={(digest) => void save(digest)} />
      </section>
    </div>
  );
}
