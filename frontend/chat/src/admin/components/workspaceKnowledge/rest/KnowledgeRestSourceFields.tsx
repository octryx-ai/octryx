import type { ReactNode } from "react";
import { Field } from "../../restApis/restApisParts";
import { PairsEditor } from "../../../../chat/work/intake/WorkIntakeRestSteps";
import { roleRule } from "../../../../chat/work/intake/restIntakeModel";
import { DOT_PATH_HINT } from "../../../../chat/work/intake/restIntakeForm";
import { MAPPING_FIELDS, MEDIA_JSON, MEDIA_TYPES, withContentFrom } from "./restSourceForm";
import { RESTRICTED_TEXT, WORKSPACE_TEXT, detailCandidates, pathParams, visibilityRule } from "./restSourceRules";
import type { ContentFrom, RestKnowledgeForm, Visibility } from "./restSourceForm";
import type { RestOperationInfo } from "../../../../chat/work/intake/restIntakeForm";
import type { RestCatalog } from "./restSourceApi";
import "../../restApis/restApis.css";
import "../../../../chat/work/intake/workIntake.css";
import "./rest-source.css";

// The REST part of the source form (Knowledge › Sources): what it reads and as whom, where the content comes
// from, the mapping, and who finds the items. Each problem shows at its field (server field names as keys).

type Props = {
  form: RestKnowledgeForm;
  set: (next: RestKnowledgeForm) => void;
  catalog: RestCatalog;
  errors: Record<string, string>;
  isPlatformAdmin: boolean;
  editing: boolean;
};

const operationLabel = (operation: RestOperationInfo) => `${operation.name} · ${operation.method} ${operation.path}`;

const CONTENT_CHOICES: Array<{ key: ContentFrom; label: string; text: string }> = [
  { key: "record", label: "The listed record", text: "The whole record becomes readable text. Nothing else is called." },
  { key: "detail", label: "A detail operation", text: "One read per changed record, with its id, returns the full content." },
  { key: "field", label: "One field", text: "A field of the listed record holds the text, for example body." },
];

function Section({ title, children, testId }: { title: string; children: ReactNode; testId?: string }) {
  return (
    <fieldset className="ds-form-section" data-testid={testId}>
      <legend className="ds-form-section__title">{title}</legend>
      <div className="ds-form-section__body">{children}</div>
    </fieldset>
  );
}

function Choice({ name, checked, disabled, onChange, label, text, testId }: {
  name: string; checked: boolean; disabled?: boolean; onChange: () => void; label: string; text: ReactNode; testId?: string;
}) {
  return (
    <label className="admin-option-card rest-source__choice" data-testid={testId}>
      <input type="radio" name={name} checked={checked} disabled={disabled} onChange={onChange} />
      <span><b>{label}</b><span>{text}</span></span>
    </label>
  );
}

function WhatItReads({ form, set, catalog, errors, editing }: Props) {
  const patch = (next: Partial<RestKnowledgeForm>) => set({ ...form, ...next });
  const operations = catalog.operations ?? [];
  const operation = operations.find((entry) => entry.op_key === form.operation);
  const rule = roleRule(operation, form.role);
  return (
    <Section title="What it reads" testId="rest-source-what">
      <Field label="REST API" error={errors["scope.definition"]} testId="rest-source-definition"
        hint={catalog.apis && !catalog.apis.length ? "This Workspace reaches no REST API with a granted read operation. A platform admin adds one in Connections › REST APIs." : undefined}>
        <select className="admin-panel__input" value={form.definition} disabled={editing || !catalog.apis}
          onChange={(event) => set({ ...form, definition: event.target.value, operation: "", role: "", detailOperation: "", detailParam: "" })}>
          <option value="">{catalog.apis ? "Pick a REST API" : "Reading the REST APIs…"}</option>
          {(catalog.apis ?? []).map((api) => (
            <option key={api.id} value={api.id}>{api.connected ? api.name : `${api.name} (no connection in this Workspace)`}</option>
          ))}
        </select>
      </Field>
      {form.definition ? (
        <Field label="List operation" error={errors["scope.operation"]} testId="rest-source-operation"
          hint={operation ? [operation.summary, operation.paginated ? "Reads page by page." : ""].filter(Boolean).join(". ") || undefined
            : catalog.operations && !operations.length ? "This API has no enabled read operation. Enable one in Connections › REST APIs." : "Only enabled read operations are offered."}>
          <select className="admin-panel__input" value={form.operation} disabled={!catalog.operations}
            onChange={(event) => {
              const next = operations.find((entry) => entry.op_key === event.target.value);
              patch({ operation: event.target.value, role: next && next.roles.length === 1 ? next.roles[0] : "" });
            }}>
            <option value="">{catalog.operations ? "Pick an operation" : "Reading the operations…"}</option>
            {operations.map((entry) => <option key={entry.op_key} value={entry.op_key}>{operationLabel(entry)}</option>)}
          </select>
        </Field>
      ) : null}
      {operation ? (
        <>
          {rule.required ? (
            <p className="rest-source__note" role="note" data-testid="rest-source-role-required">
              <b>A role is required.</b> This operation's grants have a scope (for example a group or a customer). The sync
              reads as the role you pick, and its scope is enforced as that role, so the source only reads what that role may see.
            </p>
          ) : null}
          <Field label="Read as role" error={errors["scope.role"] ?? (form.role ? rule.problem : null)} testId="rest-source-role"
            hint={rule.required ? "Required: the roles below hold a grant of this operation." : "Optional: without scoped grants the sync reads as a granted role."}>
            <select className="admin-panel__input" value={form.role} onChange={(event) => patch({ role: event.target.value })}>
              <option value="">{rule.required ? "Pick a role" : "Any granted role"}</option>
              {rule.roles.map((role) => (
                <option key={role} value={role}>{operation.scoped_roles.includes(role) ? `${role} (scoped)` : role}</option>
              ))}
            </select>
          </Field>
          <PairsEditor label="Fixed arguments" pairs={form.arguments} onChange={(next) => patch({ arguments: next })}
            hint="Sent with every call, for example state = published. The role's scope is added last and always wins." />
          {errors["scope.arguments"] ? <p className="rst-field__error" role="alert">{errors["scope.arguments"]}</p> : null}
          <Field label="Changed-since argument" error={errors["scope.updated_since_param"]}
            hint="Optional: an argument of the list operation that returns only records changed since a time. Scheduled syncs then read less.">
            <input className="admin-panel__input work-mono" value={form.updatedSinceParam} placeholder="changed_since"
              onChange={(event) => patch({ updatedSinceParam: event.target.value.trim() })} />
          </Field>
        </>
      ) : null}
    </Section>
  );
}

function ContentSource({ form, set, catalog, errors }: Props) {
  const patch = (next: Partial<RestKnowledgeForm>) => set({ ...form, ...next });
  const candidates = detailCandidates(catalog.operations ?? [], form.operation);
  const detail = candidates.find((entry) => entry.op_key === form.detailOperation);
  const params = pathParams(detail?.path);
  const showMedia = form.contentFrom !== "record";
  return (
    <Section title="Content" testId="rest-source-content">
      <div className="rest-source__choices" role="radiogroup" aria-label="Where the content comes from">
        {CONTENT_CHOICES.map((choice) => (
          <Choice key={choice.key} name="rest-content-from" checked={form.contentFrom === choice.key} label={choice.label}
            text={choice.text} testId={`rest-source-content-${choice.key}`} onChange={() => set(withContentFrom(form, choice.key))} />
        ))}
      </div>
      {form.contentFrom === "detail" ? (
        <div className="rest-source__grid">
          <Field label="Detail operation" error={errors["scope.detail_operation"]} testId="rest-source-detail"
            hint={candidates.length ? "A read operation of the same API with the record's id in its path." : "This API has no other read operation with a path argument."}>
            <select className="admin-panel__input" value={form.detailOperation}
              onChange={(event) => {
                const next = candidates.find((entry) => entry.op_key === event.target.value);
                const nextParams = pathParams(next?.path);
                patch({ detailOperation: event.target.value, detailParam: nextParams.length === 1 ? nextParams[0] : "" });
              }}>
              <option value="">Pick an operation</option>
              {candidates.map((entry) => <option key={entry.op_key} value={entry.op_key}>{operationLabel(entry)}</option>)}
            </select>
          </Field>
          <Field label="Id goes into" error={errors["scope.detail_param"]} testId="rest-source-detail-param"
            hint="The argument that takes the record's mapped id.">
            <select className="admin-panel__input" value={form.detailParam} disabled={!detail}
              onChange={(event) => patch({ detailParam: event.target.value })}>
              {params.length !== 1 ? <option value="">Pick an argument</option> : null}
              {params.map((param) => <option key={param} value={param}>{`{${param}}`}</option>)}
            </select>
          </Field>
        </div>
      ) : null}
      {showMedia ? (
        <div className="rest-source__grid">
          <Field label={form.contentFrom === "detail" ? "Content field in the answer" : "Content field *"} error={errors["mapping.content"]}
            testId="rest-source-content-path"
            hint={form.contentFrom === "detail" && form.mediaType === MEDIA_JSON ? "Optional: empty takes the whole answer as text." : "A dot path, like body or article.text."}>
            <input className="admin-panel__input work-mono" value={form.contentPath} placeholder="body"
              onChange={(event) => patch({ contentPath: event.target.value })} />
          </Field>
          <Field label="Content type" error={errors["scope.media_type"]} testId="rest-source-media"
            hint={form.mediaType === "text/html" || form.mediaType === "application/pdf" ? "Read in the document parser sandbox." : undefined}>
            <select className="admin-panel__input" value={form.mediaType} onChange={(event) => patch({ mediaType: event.target.value })}>
              {MEDIA_TYPES.map((media) => <option key={media.value} value={media.value}>{media.label}</option>)}
            </select>
          </Field>
        </div>
      ) : null}
    </Section>
  );
}

function Mapping({ form, set, errors }: Props) {
  return (
    <Section title="Mapping" testId="rest-source-mapping">
      <p className="rst-muted">{DOT_PATH_HINT}</p>
      <div className="rest-source__grid">
        {MAPPING_FIELDS.map((field) => (
          <Field key={field.name} label={field.label} error={errors[`mapping.${field.name}`]} hint={field.hint}
            testId={`rest-source-map-${field.name}`}>
            <input className="admin-panel__input work-mono" value={form.mapping[field.name]} placeholder={field.placeholder}
              onChange={(event) => set({ ...form, mapping: { ...form.mapping, [field.name]: event.target.value } })} />
          </Field>
        ))}
      </div>
    </Section>
  );
}

function WhoFinds({ form, set, errors, isPlatformAdmin }: Props) {
  const rule = visibilityRule(isPlatformAdmin);
  const choose = (visibility: Visibility) => set({ ...form, visibility });
  return (
    <Section title="Who finds the items" testId="rest-source-visibility">
      <div className="rest-source__choices" role="radiogroup" aria-label="Who finds the items">
        <Choice name="rest-visibility" checked={form.visibility === "restricted"} onChange={() => choose("restricted")}
          label="Restricted by grant (default)" text={RESTRICTED_TEXT} testId="rest-source-visibility-restricted" />
        <Choice name="rest-visibility" checked={form.visibility === "workspace"} disabled={!rule.workspaceAllowed}
          onChange={() => choose("workspace")} label="Everyone in the Workspace" testId="rest-source-visibility-workspace"
          text={rule.hint ? <>{WORKSPACE_TEXT} <em>{rule.hint}</em></> : WORKSPACE_TEXT} />
      </div>
      {errors["scope.visibility"] ? <p className="rst-field__error" role="alert">{errors["scope.visibility"]}</p> : null}
    </Section>
  );
}

export function KnowledgeRestSourceFields(props: Props) {
  return (
    <div className="rest-source" data-testid="rest-source-fields">
      {props.catalog.problem ? <p className="rst-error" role="alert">{props.catalog.problem}</p> : null}
      <WhatItReads {...props} />
      <ContentSource {...props} />
      <Mapping {...props} />
      <WhoFinds {...props} />
    </div>
  );
}
