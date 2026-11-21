import { useMemo, useState } from "react";

import { SegmentedTabs } from "../../../layout/SegmentedTabs";
import { StatusLabel } from "../../../layout/StatusLabel";
import { ConfirmDialog } from "../confirm/ConfirmDialog";
import { RestGrantEditor } from "./RestGrantEditor";
import { RestOperationSetup } from "./RestOperationSetup";
import { RestTestCall } from "./RestTestCall";
import { deleteOperation, updateOperation, type RestDefinition, type RestOperation } from "./restApisApi";
import { callsHref } from "./restCallsModel";
import { grantProblems, hasProblems, isReadDraft, operationBody, operationDraft, operationWarnings, unsavedHint, type OperationDraft } from "./restOperationEditorModel";
import { operationKind, operationState, serverWarnings, toolNameFor } from "./restOperationsModel";
import { restErrorView, type RestErrorView } from "./restErrorsModel";
import { FormError, Mono, Warnings } from "./restApisParts";
import type { Workspace } from "./RestApisPage";

type Tab = "setup" | "access" | "test";

// The error fields a tab shows at its own field; any other error is shown above the save row.
const FIELD_ERRORS = ["llm_name", "overlay", "response_select", "records_path", "pagination", "grants", "capability", "idempotent", "enabled", "template"];

// One operation: Setup (on/off, what the model sees, parameters, response), Access (grants with their data scope) and
// a Test call. Setup and Access are one draft with one Save; the warnings follow the draft while it is edited.
export function RestOperationEditor({ definition, operation, workspaces, onBack, onSaved, onDeleted }: {
  definition: RestDefinition;
  operation: RestOperation;
  workspaces: Workspace[];
  onBack: () => void;
  onSaved: () => void;
  onDeleted: () => void;
}) {
  const [tab, setTab] = useState<Tab>("setup");
  const [draft, setDraft] = useState<OperationDraft>(() => operationDraft(operation));
  const [saved, setSaved] = useState<OperationDraft>(() => operationDraft(operation));
  const [error, setError] = useState<RestErrorView | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
  // Saved: the server's warnings that name this operation (backend). Unsaved edits: the editor's own hints, marked
  // as such. On Access each grant shows its own scope hint, so the list on top leaves those out there.
  const warnings = useMemo(() => (dirty
    ? operationWarnings(operation, draft, tab !== "access").map(unsavedHint)
    : serverWarnings(definition).filter((warning) => warning.opId === operation.id).map((warning) => warning.text)),
  [dirty, definition, operation, draft, tab]);
  const blocked = draft.grants.some((grant) => hasProblems(grantProblems(grant)));

  const save = () => saveOperation({ definitionId: definition.id, operation, draft, setBusy, setError, setSaved, onSaved });

  const remove = async () => {
    try {
      await deleteOperation(definition.id, operation.id);
      setConfirming(false);
      onDeleted();
    } catch (failure) {
      setDeleteError(restErrorView(failure).text);
    }
  };

  return (
    <div className="rst-stack" data-testid="rest-operation-editor">
      <button type="button" className="ds-link-button rst-back" onClick={onBack} data-testid="rest-operation-back">‹ All operations</button>
      <OperationHead definition={definition} operation={operation} draft={draft} />
      <SegmentedTabs size="small" label="Operation sections" idPrefix="rest-op" value={tab} onChange={(next) => setTab(next as Tab)}
        tabs={operationTabs(draft.grants.length)} />
      <OperationSection tab={tab} warnings={warnings} definition={definition} operation={operation} workspaces={workspaces}
        draft={draft} saved={saved} setDraft={setDraft} error={error} />
      {tab !== "test" ? (
        <OperationSaveRow error={error} dirty={dirty} busy={busy} blocked={blocked} onSave={() => void save()}
          onDelete={() => { setDeleteError(null); setConfirming(true); }} onDiscard={() => { setDraft(saved); setError(null); }} />
      ) : null}
      {confirming ? (
        <DeleteOperationDialog operation={operation} error={deleteError} onConfirm={() => void remove()} onCancel={() => setConfirming(false)} />
      ) : null}
    </div>
  );
}

// Saves the draft; the saved draft becomes the new baseline, a refusal is kept for its field.
async function saveOperation({ definitionId, operation, draft, setBusy, setError, setSaved, onSaved }: {
  definitionId: string;
  operation: RestOperation;
  draft: OperationDraft;
  setBusy: (busy: boolean) => void;
  setError: (error: RestErrorView | null) => void;
  setSaved: (draft: OperationDraft) => void;
  onSaved: () => void;
}) {
  setBusy(true);
  setError(null);
  try {
    await updateOperation(definitionId, operation.id, operationBody(operation, draft));
    setSaved(draft);
    onSaved();
  } catch (failure) {
    setError(restErrorView(failure));
  } finally {
    setBusy(false);
  }
}

const operationTabs = (grants: number) => [
  { key: "setup", label: "Setup", testId: "rest-op-tab-setup" },
  { key: "access", label: "Access", count: grants, testId: "rest-op-tab-access" },
  { key: "test", label: "Test call", testId: "rest-op-tab-test" },
];

// The open tab: the warnings above Setup and Access, then Setup, Access (grants) or the test call.
function OperationSection({ tab, warnings, definition, operation, workspaces, draft, saved, setDraft, error }: {
  tab: Tab;
  warnings: string[];
  definition: RestDefinition;
  operation: RestOperation;
  workspaces: Workspace[];
  draft: OperationDraft;
  saved: OperationDraft;
  setDraft: (draft: OperationDraft) => void;
  error: RestErrorView | null;
}) {
  return (
    <>
      {tab !== "test" ? <Warnings items={warnings} testId="rest-operation-warnings" /> : null}
      {tab === "setup" ? <RestOperationSetup operation={operation} defaultPreset={definition.default_preset} draft={draft} onChange={setDraft} error={error} /> : null}
      {tab === "access" ? (
        <RestGrantEditor operation={operation} draft={draft} saved={saved.grants} onChange={setDraft} workspaces={workspaces}
          error={error?.field === "grants" ? error.text : null} />
      ) : null}
      {tab === "test" ? <RestTestCall definition={definition} operation={operation} workspaces={workspaces} write={!operation.is_read} /> : null}
    </>
  );
}

function DeleteOperationDialog({ operation, error, onConfirm, onCancel }: {
  operation: RestOperation; error: string | null; onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <ConfirmDialog title={`Delete ${operation.op_key}?`} confirmLabel="Delete operation" error={error}
      onConfirm={onConfirm} onCancel={onCancel}>
      <p>Agents lose the tool {operation.tool_name} and its grants are removed. Past calls stay in the audit.</p>
    </ConfirmDialog>
  );
}

// The operation's method, path, kind, state, tool name, summary and the link to its calls.
function OperationHead({ definition, operation, draft }: { definition: RestDefinition; operation: RestOperation; draft: OperationDraft }) {
  const state = operationState({ enabled: draft.enabled, grants: draft.grants, unsupported: operation.unsupported });
  const kind = operationKind({ is_read: isReadDraft(operation, draft), capability: draft.capability });
  return (
    <div className="rst-op-head">
      <div className="rst-row">
        <span className="rst-method">{operation.method}</span>
        <span className="rst-name__main">{operation.path}</span>
        <span className={kind.write ? "rst-kind rst-kind--write" : "rst-kind"} title={kind.hint || undefined}
          data-testid="rest-operation-kind">{kind.label}</span>
        <StatusLabel label={state.label} tone={state.tone} title={state.hint} />
      </div>
      <Mono>{toolNameFor(definition.key, { op_key: operation.op_key, llm_name: draft.llmName })}</Mono>
      {operation.summary ? <p className="rst-muted">{operation.summary}</p> : null}
      <a className="ds-link-button rst-back" href={callsHref(definition.id, operation.id)} data-testid="rest-operation-calls">Calls of this operation ›</a>
    </div>
  );
}

// Below Setup and Access: an error without a field of its own, then Delete, Discard and Save.
function OperationSaveRow({ error, dirty, busy, blocked, onSave, onDelete, onDiscard }: {
  error: RestErrorView | null; dirty: boolean; busy: boolean; blocked: boolean;
  onSave: () => void; onDelete: () => void; onDiscard: () => void;
}) {
  return (
    <>
      <FormError text={error && !FIELD_ERRORS.includes(error.field ?? "") ? error.text : null} />
      <div className="rst-row rst-row--end">
        <button type="button" className="ds-btn ds-btn--ghost" onClick={onDelete}
          data-testid="rest-operation-delete">Delete operation…</button>
        <button type="button" className="ds-btn" disabled={!dirty || busy} onClick={onDiscard}>Discard</button>
        <button type="button" className="ds-btn ds-btn--primary" disabled={!dirty || busy || blocked} onClick={onSave}
          data-testid="rest-operation-save">
          {busy ? "Saving…" : "Save operation"}
        </button>
      </div>
    </>
  );
}
