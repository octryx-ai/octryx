import { useState } from "react";

import { StatusLabel } from "../../../layout/StatusLabel";
import { AdminDetailFacts } from "../AdminDetailFacts";
import { testOperation, type RestDefinition, type RestOperation } from "./restApisApi";
import { TEST_NOTE, TEST_WRITE_NOTE } from "./restOperationsModel";
import { durationText } from "./restCallsModel";
import { restErrorView } from "./restErrorsModel";
import { testBody, testParameters, testView, type TestDraft, type TestView } from "./restTestCallModel";
import { wireNameOf } from "./restOdataModel";
import { Field, FormError } from "./restApisParts";
import type { Workspace } from "./RestApisPage";

// A test call of one operation as the signed-in admin: the same executor, grants, scope and audit as an agent's call.
// The answer shows the result, the applied scope, records kept and dropped, the status and the duration (the run's
// own duration_ms, backend). A write is never test-called (backend answers 400: the test call bypasses the
// approval), so a write shows that up front instead of a button.
export function RestTestCall({ definition, operation, workspaces, write }: {
  definition: RestDefinition;
  operation: RestOperation;
  workspaces: Workspace[];
  write: boolean;
}) {
  if (write) {
    return (
      <div className="rst-stack" data-testid="rest-test-call">
        <p className="rst-note" data-testid="rest-test-write-note">{TEST_WRITE_NOTE}</p>
        <p className="rst-muted">Every write call appears under Calls with the approval or write plan that admitted it.</p>
      </div>
    );
  }
  return <RestReadTestCall definition={definition} operation={operation} workspaces={workspaces} />;
}

function RestReadTestCall({ definition, operation, workspaces }: {
  definition: RestDefinition;
  operation: RestOperation;
  workspaces: Workspace[];
}) {
  const fields = testParameters(operation);
  const [draft, setDraft] = useState<TestDraft>({ workspaceId: "", mode: "form", values: {}, json: "{}" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<TestView | null>(null);

  const run = async () => {
    const built = testBody(operation, draft);
    if ("error" in built) { setError(built.error); return; }
    setBusy(true);
    setError(null);
    try {
      setView(testView(await testOperation(definition.id, operation.id, built.body)));
    } catch (failure) {
      setError(restErrorView(failure).text);
      setView(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rst-stack" data-testid="rest-test-call">
      <p className="rst-note">{TEST_NOTE}</p>
      <div className="rst-grid">
        <Field label="Workspace (optional)" hint="Picks the Workspace's connection and grants.">
          <select className="admin-panel__input" value={draft.workspaceId} onChange={(event) => setDraft({ ...draft, workspaceId: event.target.value })}
            data-testid="rest-test-workspace">
            <option value="">No Workspace (platform connection)</option>
            {workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}
          </select>
        </Field>
        <Field label="Arguments as">
          <select className="admin-panel__input" value={draft.mode} onChange={(event) => setDraft({ ...draft, mode: event.target.value as TestDraft["mode"] })}>
            <option value="form">Form</option>
            <option value="json">JSON</option>
          </select>
        </Field>
      </div>
      <TestArguments draft={draft} setDraft={setDraft} fields={fields} />
      <FormError text={error} />
      <div className="rst-row rst-row--end">
        <button type="button" className="ds-btn ds-btn--primary" disabled={busy} onClick={() => void run()} data-testid="rest-test-run">
          {busy ? "Calling…" : "Run test call"}
        </button>
      </div>
      {view ? <TestResult view={view} /> : null}
    </div>
  );
}

// The arguments: a JSON object, or one field per parameter the admin may set (hidden and fixed ones are set by Octryx).
function TestArguments({ draft, setDraft, fields }: {
  draft: TestDraft; setDraft: (next: TestDraft) => void; fields: ReturnType<typeof testParameters>;
}) {
  return draft.mode === "json" ? (
    <Field label="Arguments (JSON object)">
      <textarea className="admin-panel__input rst-code" rows={6} value={draft.json} spellCheck={false} onChange={(event) => setDraft({ ...draft, json: event.target.value })} />
    </Field>
  ) : fields.length ? (
    <div className="rst-grid">
      {fields.map((param) => (
        <Field key={param.name} label={`${param.name}${param.required ? "" : " (optional)"}`}
          hint={wireNameOf(param) ? <><span className="rst-wire">{`sent as ${wireNameOf(param)}`}</span>{param.schema?.type === "array" ? " · values separated by commas" : ""}{param.description ? ` · ${param.description}` : ""}</> : param.description || undefined}>
          <input className="admin-panel__input" value={draft.values[param.name] ?? ""} data-testid={`rest-test-arg-${param.name}`}
            onChange={(event) => setDraft({ ...draft, values: { ...draft.values, [param.name]: event.target.value } })} />
        </Field>
      ))}
    </div>
  ) : <p className="rst-muted">No arguments to fill in: hidden and fixed parameters are set by Octryx.</p>;
}

// The answer: title and status, the message, the facts of the call and, for a success, the data.
function TestResult({ view }: { view: TestView }) {
  return (
    <section className="rst-card" data-testid="rest-test-result">
      <div className="rst-card__head">
        <h3 className="rst-card__title">{view.title}</h3>
        <StatusLabel label={view.status} tone={view.ok ? "neutral" : view.status === "Refused" ? "attention" : "problem"} />
      </div>
      {view.message ? <p className="rst-text">{view.message}</p> : null}
      <AdminDetailFacts facts={[
        { label: "HTTP status", value: view.httpStatus === null ? "Not sent" : String(view.httpStatus) },
        { label: "Applied scope", value: view.ok ? view.scope : "" },
        { label: "Records kept", value: view.kept === null ? "" : String(view.kept) },
        { label: "Dropped as out of scope", value: view.ok || view.dropped ? String(view.dropped) : "" },
        { label: "Duration", value: durationText(view.durationMs) },
      ]} />
      {view.ok ? <pre className="rst-result" data-testid="rest-test-data">{JSON.stringify(view.data, null, 2)}</pre> : null}
    </section>
  );
}
