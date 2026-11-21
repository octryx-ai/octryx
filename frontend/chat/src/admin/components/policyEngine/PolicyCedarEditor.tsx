import { Suspense, useCallback, useState } from "react";
import type { ComponentType } from "react";

import type { CedarEditorProps } from "./CedarPolicyEditor";
import type { LiveIssue } from "./cedarValidation";
import { savePolicy, validatePolicies } from "./policyEngineApi";
import { readIssues, refusalText } from "./policyEngineVersions";
import type { PolicyIssue } from "./policyEngineVersions";
import type { PolicyView } from "./policyCatalogModel";

export type CedarSession = { text: string; originalId: string | null; isNew: boolean; title: string };

const idOf = (text: string) => /@id\(\s*"((?:[^"\\]|\\.)*)"\s*\)/.exec(text)?.[1] ?? "";

// One hand-written policy in the dark Cedar editor: what the builder cannot express (OR across
// steps, nested logic). The server checks the statement, saves it into the draft (policy-level save, If-Match) and
// runs the saved test cases. A builder policy converted with "Edit as Cedar…" arrives here without @builder.
export function PolicyCedarEditor({ editor: EditorComponent, schema, session, view, onCancel, onSaved }: {
  editor: ComponentType<CedarEditorProps>;
  schema: string;
  session: CedarSession;
  view: PolicyView;
  onCancel: () => void;
  onSaved: (message: string) => Promise<void>;
}) {
  const [text, setText] = useState(session.text);
  const [showDiff, setShowDiff] = useState(false);
  const [issues, setIssues] = useState<PolicyIssue[]>([]);
  const [live, setLive] = useState<LiveIssue[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const onLiveIssues = useCallback((next: LiveIssue[] | null) => setLive(next), []);
  const target = view.editTarget;
  const policyId = idOf(text);

  const save = async () => {
    if (!target) return;
    setBusy(true);
    setProblem(null);
    try {
      const answer = await validatePolicies(text) as { valid?: unknown };
      const found = readIssues(answer);
      setIssues(found);
      if (answer.valid !== true) {
        setProblem("The server refuses this policy.");
        return;
      }
      await savePolicy(target.version, session.originalId ?? policyId, { cedar: text, create: session.isNew }, target.digest);
      await onSaved(`Saved "${policyId}" to the draft as hand-written Cedar; the saved test cases ran against it.`);
    } catch (error) {
      setProblem(refusalText(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="policies__pane" data-testid="policy-cedar-editor">
      <div className="policies__flex-between">
        <div className="policies__row">
          <button type="button" className="admin-panel__action-btn" data-testid="policy-cedar-back" onClick={onCancel}>← Policies</button>
          <span className="admin-panel__title">{session.title}</span>
          <span className="work-badge work-badge--neutral">Hand-written</span>
          <span className="work-badge work-badge--attention">{!target ? "Draft in review (frozen)" : target.createsDraft ? "Creates a new draft" : `Saves into draft v${target.version}`}</span>
        </div>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="policy-cedar-save"
          disabled={busy || !target || !policyId || (text === session.text && !session.isNew)} onClick={() => void save()}>Save to draft</button>
      </div>
      <section className="admin-panel__card policies__pane">
        <p className="admin-panel__hint">One <span className="admin-policy-inline-code">forbid</span> with a unique <span className="admin-policy-inline-code">@id</span>. It narrows the generated baseline and always wins over it.</p>
        {!session.isNew ? (
          <label className="policies__row policies__src">
            <input type="checkbox" checked={showDiff} data-testid="policy-cedar-diff" onChange={(event) => setShowDiff(event.target.checked)} />
            Compare with the saved text
          </label>
        ) : null}
        <Suspense fallback={<p className="admin-panel__hint">Loading the editor…</p>}>
          <EditorComponent value={text} onChange={(next) => { setText(next); setIssues([]); }} readOnly={busy || !target}
            schema={schema} original={session.text} showDiff={showDiff} onLiveIssues={onLiveIssues} />
        </Suspense>
        <p className="admin-panel__hint" data-testid="policy-cedar-live">
          {live === null ? "Live validation is not available in this browser; the server validates on save."
            : live.length ? `${live.length} problem${live.length === 1 ? "" : "s"} found while typing.` : "No problem found while typing."}
        </p>
        {issues.length ? (
          <ul className="workspace-classification__message" role="alert" data-testid="policy-cedar-issues">
            {issues.map((item, index) => <li key={`${item.policyId}-${index}`}>{item.policyId ? `${item.policyId}: ` : ""}{item.message}</li>)}
          </ul>
        ) : null}
        {problem ? <p className="workspace-classification__message" role="alert" data-testid="policy-cedar-problem">{problem}</p> : null}
      </section>
    </div>
  );
}
