import { useState } from "react";

import { AdvancedSection } from "../../../layout/FormSection";
import { DataTable, type DataTableColumn } from "../../../layout/DataTable";
import { StatusLabel } from "../../../layout/StatusLabel";
import { addOperation, updateOperation, type OdataTemplate, type RestDefinition, type RestOperation } from "./restApisApi";
import { BY_HAND, ODATA_TEMPLATES, templateHint } from "./restOdataModel";
import { CAPABILITY_NOTE, WRITES_NEED_APPROVAL, grantCountText, operationKind, operationState } from "./restOperationsModel";
import { manualOperationBody, type ManualOperationDraft } from "./restDefinitionDraftsModel";
import { restErrorView, type RestErrorView } from "./restErrorsModel";
import { Field, FormError, Mono } from "./restApisParts";

const METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"];
const emptyDraft: ManualOperationDraft = { opKey: "", method: "GET", path: "", summary: "", query: "" };

// The table's columns: method, path with the tool name agents see, read or write (with its run class), state and grants.
const OPERATION_COLUMNS: DataTableColumn<RestOperation>[] = [
  { key: "method", header: "Method", nowrap: true, render: (op) => <span className="rst-method">{op.method}</span> },
  {
    key: "path", header: "Path and tool", grow: true, minWidth: "10rem",
    render: (op) => (
      <span className="rst-name">
        <span className="rst-name__main">{op.path}</span>
        <Mono>{op.tool_name}</Mono>
      </span>
    ),
  },
  {
    key: "kind", header: "Kind", nowrap: true,
    render: (op) => {
      const kind = operationKind(op);
      return <span className={kind.write ? "rst-kind rst-kind--write" : "rst-kind"} title={kind.hint || undefined}
        data-testid={`rest-op-kind-${op.op_key}`}>{kind.label}</span>;
    },
  },
  {
    key: "state", header: "State", nowrap: true,
    render: (op) => {
      const state = operationState(op);
      return <StatusLabel label={state.label} tone={state.tone} title={state.hint} />;
    },
  },
  { key: "grants", header: "Grants", nowrap: true, align: "end", render: (op) => grantCountText(op.grants.length) },
];

// The operations of one API: method, path, the tool name agents see, read or write (with the run class a write needs),
// whether it is on and for how many roles. A row opens the editor. Below, an operation can be added by hand (it arrives off, like an imported one).
export function RestOperationList({ definition, onOpen, onAdded }: {
  definition: RestDefinition;
  onOpen: (id: string) => void;
  onAdded: () => void;
}) {
  const [draft, setDraft] = useState<ManualOperationDraft>(emptyDraft);
  const [error, setError] = useState<RestErrorView | null>(null);
  const [template, setTemplate] = useState<OdataTemplate | "">("");
  const [busy, setBusy] = useState(false);
  const operations = definition.operations ?? [];

  const add = async () => {
    setBusy(true);
    setError(null);
    try {
      const added = await addOperation(definition.id, manualOperationBody(draft));
      // The template is set on the new operation (PUT {preset}); it arrives off either way.
      if (template && draft.method === "GET") await updateOperation(definition.id, added.id, { preset: template });
      setDraft(emptyDraft);
      setTemplate("");
      onAdded();
    } catch (failure) {
      setError(restErrorView(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rst-stack">
      <DataTable<RestOperation>
        label="Operations"
        testId="rest-operation-table"
        rows={operations}
        rowKey={(op) => op.id}
        onOpen={(op) => onOpen(op.id)}
        empty={{ text: "No operations yet. Add one by hand below.", testId: "rest-operations-empty" }}
        columns={OPERATION_COLUMNS}
      />
      {operations.some((op) => !op.is_read) ? (
        <div className="rst-note" data-testid="rest-writes-note">
          <p>{WRITES_NEED_APPROVAL}</p>
          <p className="rst-muted">{CAPABILITY_NOTE}</p>
        </div>
      ) : null}
      <AddOperationForm draft={draft} setDraft={setDraft} template={template} setTemplate={setTemplate} error={error} busy={busy}
        onAdd={() => void add()} />
    </div>
  );
}

function AddOperationForm({ draft, setDraft, template, setTemplate, error, busy, onAdd }: {
  draft: ManualOperationDraft;
  setDraft: (next: ManualOperationDraft) => void;
  template: OdataTemplate | "";
  setTemplate: (next: OdataTemplate | "") => void;
  error: RestErrorView | null;
  busy: boolean;
  onAdd: () => void;
}) {
  const at = (field: string) => (error?.field === field ? error.text : null);
  return (
    <AdvancedSection label="Add an operation by hand" testId="rest-add-operation">
      <div className="rst-grid">
        <Field label="Operation key" error={at("op_key")}>
          <input className="admin-panel__input" value={draft.opKey} onChange={(event) => setDraft({ ...draft, opKey: event.target.value })} placeholder="list_tickets" />
        </Field>
        <Field label="Method" error={at("method")}>
          <select className="admin-panel__input" value={draft.method} onChange={(event) => setDraft({ ...draft, method: event.target.value })}>
            {METHODS.map((method) => <option key={method} value={method}>{method}</option>)}
          </select>
        </Field>
      </div>
      <Field label="Path" hint="Path parameters in braces, e.g. /tickets/{id}." error={at("path")}>
        <input className="admin-panel__input" value={draft.path} onChange={(event) => setDraft({ ...draft, path: event.target.value })} placeholder="/tickets/{id}" />
      </Field>
      <Field label="Query parameters (optional)" hint="Names separated by commas." error={at("parameters")}>
        <input className="admin-panel__input" value={draft.query} onChange={(event) => setDraft({ ...draft, query: event.target.value })} placeholder="status, assignment_group" />
      </Field>
      {draft.method === "GET" ? (
        <Field label="Template (optional)" hint={template ? templateHint(template) : "For an OData collection: where the records and the next page are."}>
          <select className="admin-panel__input" value={template} onChange={(event) => setTemplate(event.target.value as OdataTemplate | "")}
            data-testid="rest-add-operation-template">
            <option value="">{BY_HAND}</option>
            {ODATA_TEMPLATES.map((entry) => <option key={entry.value} value={entry.value}>{entry.label}</option>)}
          </select>
        </Field>
      ) : null}
      <Field label="Summary (optional)">
        <input className="admin-panel__input" value={draft.summary} onChange={(event) => setDraft({ ...draft, summary: event.target.value })} />
      </Field>
      <FormError text={error && !["op_key", "method", "path", "parameters"].includes(error.field ?? "") ? error.text : null} />
      <div className="rst-row rst-row--end">
        <button type="button" className="ds-btn" disabled={busy || !draft.opKey || !draft.path} onClick={onAdd}>
          {busy ? "Adding…" : "Add operation"}
        </button>
      </div>
    </AdvancedSection>
  );
}
