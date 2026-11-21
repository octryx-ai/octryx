import { useCallback, useEffect, useState } from "react";

import { generateExamples, saveTestCase } from "./policyEngineApi";
import { refusalText } from "./policyEngineVersions";
import { exampleCase, readImpact } from "./policyLifecycleModel";
import type { Impact } from "./policyLifecycleModel";
import { PolicyRef } from "./PolicyRef";
import { PolicyTestReport } from "./PolicyTestReport";
import "./policyDrawers.css";

// "What would this block?": generated questions the policy must block and one it must
// leave alone, answered by the test bench against the draft with this policy, and the saved test cases against the
// same candidate. Each example can be saved as a test case that records the intent (block → deny, control → allow).
export function PolicyImpact({ model, originalId, policyName, auto = true, onOpenBench }: {
  model: unknown;
  originalId: string | null;
  policyName: string;
  auto?: boolean;
  onOpenBench?: () => void;
}) {
  const [impact, setImpact] = useState<Impact | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const run = useCallback(async () => {
    setBusy(true);
    setMessage(null);
    try {
      setImpact(readImpact(await generateExamples(model, originalId)));
    } catch (error) {
      setMessage({ ok: false, text: refusalText(error) });
    } finally {
      setBusy(false);
    }
  }, [model, originalId]);

  useEffect(() => { if (auto) void run(); }, [auto, run]);

  const save = async (indexes: number[]) => {
    if (!impact) return;
    setBusy(true);
    try {
      for (const index of indexes) await saveTestCase(exampleCase(impact.examples[index], policyName));
      setMessage({ ok: true, text: indexes.length === 1 ? "Saved as a test case." : `${indexes.length} examples saved as test cases.` });
    } catch (error) {
      setMessage({ ok: false, text: refusalText(error) });
    } finally {
      setBusy(false);
    }
  };
  const savable = impact ? impact.examples.map((item, index) => (item.answer.error ? -1 : index)).filter((index) => index >= 0) : [];

  return (
    <div className="policies__pane" data-testid="policy-impact">
      <div className="admin-panel__section-header">
        <span>What would this block?</span>
        <span className="work-badge work-badge--neutral">{impact?.policySource ? `Test bench · ${impact.policySource}` : "Test bench"}</span>
      </div>
      {!impact ? (
        <div className="policies__row">
          <button type="button" className="admin-panel__action-btn" data-testid="policy-impact-run" disabled={busy} onClick={() => void run()}>{busy ? "Asking…" : "Run examples"}</button>
        </div>
      ) : (
        <ImpactResults impact={impact} busy={busy} savable={savable} save={save} run={run} onOpenBench={onOpenBench} />
      )}
      {message ? <p className={message.ok ? "admin-panel__success" : "workspace-classification__message"} role={message.ok ? "status" : "alert"} data-testid="policy-impact-message">{message.text}</p> : null}
    </div>
  );
}

// The answers: one row per example (blocked, allowed or an error, and whether as intended), the saves and the saved
// test cases run against the same candidate.
function ImpactResults({ impact, busy, savable, save, run, onOpenBench }: {
  impact: Impact;
  busy: boolean;
  savable: number[];
  save: (indexes: number[]) => Promise<void>;
  run: () => Promise<void>;
  onOpenBench?: () => void;
}) {
  return (
    <>
      {impact.workspaceName ? <p className="admin-panel__hint">Asked for the Workspace <b>{impact.workspaceName}</b>.</p> : null}
      {impact.notes.map((note) => <div key={note} className="policies__warn" data-testid="policy-impact-note">{note}</div>)}
      <div data-testid="policy-impact-examples">
        {impact.examples.map((example, index) => {
          const blocked = example.answer.decision === "deny";
          return (
            <div key={`${example.name}-${index}`} className="policies__impact-row" data-testid="policy-impact-example">
              <span className={`work-badge ${example.answer.error ? "work-badge--attention" : blocked ? "work-badge--danger" : "work-badge--active"}`}>
                {example.answer.error ? "Error" : blocked ? "Blocked" : "Allowed"}
              </span>
              <span>
                {example.name}{example.kind === "control" ? " — control" : ""}
                {example.answer.determining.length ? <> · by {example.answer.determining.map((id, at) => <span key={id}>{at ? ", " : ""}<PolicyRef id={id} className="policies__ref" /></span>)}</> : null}
                {!example.answer.asExpected ? <span className="policies__fail" data-testid="policy-impact-unexpected"> · not as intended: {example.kind === "block" ? "this policy does not block it" : "this policy blocks it"}</span> : null}
                {" "}<button type="button" className="policies__link" data-testid="policy-impact-save" disabled={busy || Boolean(example.answer.error)} onClick={() => void save([index])}>Save as test case</button>
              </span>
            </div>
          );
        })}
      </div>
      <div className="policies__row">
        <button type="button" className="admin-panel__action-btn" data-testid="policy-impact-save-all" disabled={busy || !savable.length} onClick={() => void save(savable)}>Save examples as test cases</button>
        {onOpenBench ? <button type="button" className="admin-panel__action-btn" onClick={onOpenBench}>Open in test bench</button> : null}
        <button type="button" className="admin-panel__action-btn" data-testid="policy-impact-rerun" disabled={busy} onClick={() => void run()}>Ask again</button>
      </div>
      <div className="admin-panel__section-header"><span>Saved test cases with this policy</span></div>
      {impact.cases ? <PolicyTestReport report={impact.cases} /> : null}
    </>
  );
}
