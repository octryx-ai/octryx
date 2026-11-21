import { FormSection } from "../../../layout/FormSection";
import type { OdataTemplate, PaginationType, RestOperation, RestParameter, WriteCapability } from "./restApisApi";
import { ALIAS_NOTE, BATCH_HINT, BATCH_LABEL, choosePreset, editAnswer, isBatch, isCollectionRead, presetInEffect, presetOptions, templateHint, wireNameOf, type PresetChoice } from "./restOdataModel";
import { PAGINATION_TYPES, isReadDraft, type OperationDraft, type PaginationDraft } from "./restOperationEditorModel";
import { WRITE_CAPABILITIES, WRITES_NEED_APPROVAL, idempotentAllowed } from "./restOperationsModel";
import { type RestErrorView } from "./restErrorsModel";
import { Field, Mono } from "./restApisParts";

type Props = {
  operation: RestOperation;
  // The API's default template (backend); undefined when the definition carries no `default_preset`.
  defaultPreset?: OdataTemplate | "";
  draft: OperationDraft;
  onChange: (draft: OperationDraft) => void;
  error: RestErrorView | null;
};

const PAGINATION_FIELDS: Record<PaginationType, Array<[keyof PaginationDraft, string, string]>> = {
  none: [],
  cursor: [["cursor_path", "Cursor in the answer", "next_cursor"], ["cursor_param", "Query parameter that takes it", "cursor"]],
  offset: [["offset_param", "Offset parameter", "offset"], ["limit_param", "Limit parameter", "limit"], ["page_size", "Page size", "50"]],
  next_url: [["next_path", "Next-page URL in the answer", "next"]],
  link_header: [],
};


type Section = {
  operation: RestOperation;
  draft: OperationDraft;
  set: (patch: Partial<OperationDraft>) => void;
  at: (field: string) => string | null;
};

// "Offer to agents": enabled (not for a batch), read-only search for a POST, the model's name and description.
function OfferSection({ operation, draft, set, at, isPost, read }: Section & { isPost: boolean; read: boolean }) {
  return (
    <FormSection title="Offer to agents">
      {isBatch(operation) ? (
        <div className="rst-note" data-testid="rest-op-batch">
          <p>{BATCH_LABEL}</p>
          <p className="rst-muted">{BATCH_HINT}</p>
        </div>
      ) : (
        <label className="admin-panel__checkbox">
          <input type="checkbox" checked={draft.enabled} onChange={(event) => set({ enabled: event.target.checked })}
            data-testid="rest-op-enabled" />
          Enabled (only roles with a grant get it{read ? "" : "; every write waits for an approval"})
        </label>
      )}
      {at("enabled") ? <small className="rst-field__error" role="alert">{at("enabled")}</small> : null}
      {isPost ? (
        <label className="admin-panel__checkbox">
          <input type="checkbox" checked={draft.readOnly} onChange={(event) => set({ readOnly: event.target.checked })} />
          Read-only search: this POST only reads data
        </label>
      ) : null}
      <Field label="Name for the model (optional)" hint={<>Tool name: <Mono>{`rest__…__${draft.llmName.trim() || operation.op_key}`}</Mono></>}
        error={at("llm_name")}>
        <input className="admin-panel__input" value={draft.llmName} placeholder={operation.op_key} onChange={(event) => set({ llmName: event.target.value })}
          data-testid="rest-op-llm-name" />
      </Field>
      <Field label="Description for the model" hint="Say what it returns and when to use it; similar descriptions make tools hard to tell apart.">
        <textarea className="admin-panel__input" rows={3} value={draft.llmDescription} placeholder={operation.summary || "What this operation returns"}
          onChange={(event) => set({ llmDescription: event.target.value })} />
      </Field>
    </FormSection>
  );
}

// "Write": the run class a write needs, and whether a PUT or DELETE may be repeated.
function WriteSection({ operation, draft, set, at }: Section) {
  return (
    <FormSection title="Write">
      <p className="rst-muted">{WRITES_NEED_APPROVAL}</p>
      <Field label="Run class it needs" error={at("capability")}
        hint={WRITE_CAPABILITIES.find((entry) => entry.value === draft.capability)?.hint}>
        <select className="admin-panel__input" value={draft.capability} data-testid="rest-op-capability"
          onChange={(event) => set({ capability: event.target.value as WriteCapability })}>
          {WRITE_CAPABILITIES.map((entry) => <option key={entry.value} value={entry.value}>{entry.label}</option>)}
        </select>
      </Field>
      {idempotentAllowed(operation.method) ? (
        <>
          <label className="admin-panel__checkbox">
            <input type="checkbox" checked={draft.idempotent} onChange={(event) => set({ idempotent: event.target.checked })}
              data-testid="rest-op-idempotent" />
            Safe to repeat (idempotent): a failed {operation.method.toUpperCase()} may be sent again
          </label>
          <small className="rst-hint">Mark it only if the API gives the same result when the same call arrives twice.</small>
          {at("idempotent") ? <small className="rst-field__error" role="alert">{at("idempotent")}</small> : null}
        </>
      ) : (
        <p className="rst-muted">A {operation.method.toUpperCase()} is never sent twice: a lost answer could otherwise write twice.</p>
      )}
    </FormSection>
  );
}

// One parameter: its wire name, where it goes, hidden from the model, its description and a fixed value.
function ParameterCard({ param, draft, set }: { param: RestParameter; draft: OperationDraft; set: Section["set"] }) {
  const entry = draft.overlay[param.name] ?? { description: "", hidden: false, value: "" };
  const put = (patch: Partial<typeof entry>) => set({ overlay: { ...draft.overlay, [param.name]: { ...entry, ...patch } } });
  return (
    <div className="rst-card" data-testid={`rest-param-${param.name}`}>
      <div className="rst-card__head">
        <span className="rst-row"><Mono>{param.name}</Mono>{wireNameOf(param) ? <span className="rst-wire" title="Sent to the API under this name"
          data-testid={`rest-param-wire-${param.name}`}>{`sent as ${wireNameOf(param)}`}</span> : null}<span className="rst-muted">{param.in}{param.required ? " · required" : ""}{param.schema?.type ? ` · ${String(param.schema.type)}` : ""}</span></span>
        <label className="admin-panel__checkbox">
          <input type="checkbox" checked={entry.hidden} onChange={(event) => put({ hidden: event.target.checked })} />
          Hidden from the model
        </label>
      </div>
      <div className="rst-grid">
        <Field label="Description for the model">
          <input className="admin-panel__input" value={entry.description} placeholder={param.description || "As in the document"} onChange={(event) => put({ description: event.target.value })} />
        </Field>
        <Field label="Fixed value (optional)" hint="Set on every call; the model cannot change it.">
          <input className="admin-panel__input" value={entry.value} onChange={(event) => put({ value: event.target.value })} />
        </Field>
      </div>
    </div>
  );
}

// "Parameters": one card per parameter, with the alias note when names differ on the wire.
function ParametersSection({ operation, draft, set, at }: Section) {
  const aliased = operation.parameters.some((param) => wireNameOf(param));
  return (
    <FormSection title="Parameters">
      {operation.parameters.length ? null : <p className="rst-muted">This operation has no parameters.</p>}
      {aliased ? <p className="rst-muted">{ALIAS_NOTE}</p> : null}
      {operation.parameters.map((param) => <ParameterCard key={param.name} param={param} draft={draft} set={set} />)}
      {at("overlay") ? <small className="rst-field__error" role="alert">{at("overlay")}</small> : null}
    </FormSection>
  );
}

// "Answer": the template in effect, records path, kept fields and pages.
function AnswerSection({ operation, defaultPreset, draft, onChange, set, at, read }: Section & {
  defaultPreset?: OdataTemplate | "";
  onChange: (draft: OperationDraft) => void;
  read: boolean;
}) {
  const collection = isCollectionRead(operation);
  const effective = presetInEffect(operation);
  const answer = (patch: Partial<Pick<OperationDraft, "recordsPath" | "pagination">>) => onChange(editAnswer(draft, patch));
  const chosenTemplate = draft.presetChoice === "inherit" ? (collection ? defaultPreset || "" : "") : draft.presetChoice === "none" ? "" : draft.presetChoice;
  return (
    <FormSection title="Answer">
      {read && effective ? (
        <p className="rst-muted" data-testid="rest-op-preset-effective">{collection ? `In effect: ${effective}` : effective}</p>
      ) : null}
      {read && collection ? (
        <Field label="Template" error={at("template")}
          hint={chosenTemplate ? templateHint(chosenTemplate) : draft.presetChoice === "" ? "Records path and pages as set below." : "Records as the API returns them, one page."}>
          <select className="admin-panel__input" value={draft.presetChoice} data-testid="rest-op-template"
            onChange={(event) => onChange(choosePreset(draft, event.target.value as PresetChoice, { defaultPreset, collection }))}>
            {presetOptions(defaultPreset).map((entry) => <option key={entry.value || "by-hand"} value={entry.value}>{entry.label}</option>)}
          </select>
        </Field>
      ) : null}
      <Field label="Records path (optional)" hint="Where the list of records sits, e.g. result or data.items. The result filter checks these."
        error={at("records_path")}>
        <input className="admin-panel__input" value={draft.recordsPath} onChange={(event) => answer({ recordsPath: event.target.value })} placeholder="result" />
      </Field>
      <Field label="Keep only these fields (optional)" hint="One dotted path per line; everything else is left out of the answer."
        error={at("response_select")}>
        <textarea className="admin-panel__input" rows={3} value={draft.responseSelect} onChange={(event) => set({ responseSelect: event.target.value })} placeholder={"id\ntitle\nstatus"} />
      </Field>
      <Field label="Pages" error={at("pagination")}>
        <select className="admin-panel__input" value={draft.pagination.type}
          onChange={(event) => answer({ pagination: { ...draft.pagination, type: event.target.value as PaginationType } })}>
          {PAGINATION_TYPES.map((entry) => <option key={entry.value} value={entry.value}>{entry.label}</option>)}
        </select>
      </Field>
      {PAGINATION_FIELDS[draft.pagination.type].length ? (
        <div className="rst-grid">
          {PAGINATION_FIELDS[draft.pagination.type].map(([name, label, placeholder]) => (
            <Field key={name} label={label}>
              <input className="admin-panel__input" value={draft.pagination[name]} placeholder={placeholder}
                onChange={(event) => answer({ pagination: { ...draft.pagination, [name]: event.target.value } })} />
            </Field>
          ))}
        </div>
      ) : null}
    </FormSection>
  );
}

// What the model sees of one operation and how its answer is shaped. read_only is offered only for a POST (a search
// endpoint that reads); GET and HEAD are reads anyway, every other method is a write: it needs a run class (Deliver or
// Change) and every call waits for an approval; a PUT or DELETE may be marked safe to repeat (backend).
export function RestOperationSetup({ operation, defaultPreset, draft, onChange, error }: Props) {
  const set = (patch: Partial<OperationDraft>) => onChange({ ...draft, ...patch });
  const at = (field: string) => (error?.field === field ? error.text : null);
  const isPost = operation.method.toUpperCase() === "POST" && !isBatch(operation);
  const read = isReadDraft(operation, draft);
  const section = { operation, draft, set, at };

  return (
    <div className="rst-stack" data-testid="rest-operation-setup">
      <OfferSection {...section} isPost={isPost} read={read} />

      {read ? null : <WriteSection {...section} />}

      <ParametersSection {...section} />

      <AnswerSection {...section} defaultPreset={defaultPreset} onChange={onChange} read={read} />
    </div>
  );
}
