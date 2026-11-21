import { useEffect, useState } from "react";

import { Field } from "../../../admin/components/restApis/restApisParts";
import { neutralLabel } from "../syncNames";
import type { IntakeDiscovery, IntakeDraft } from "./workIntakeDraft";
import { DOT_PATH_HINT, FIELD_LABELS, OPTIONAL_FIELDS, REQUIRED_FIELDS, emptyRestForm } from "./restIntakeForm";
import { mappingProblems, parseBodyTemplate, roleRule, statusRowProblems } from "./restIntakeModel";
import { refusalOf } from "./restIntakeRefusals";
import { sampleView } from "./restIntakeSample";
import type { Pair, RestOperationInfo, RestSourceForm } from "./restIntakeForm";
import type { SampleView } from "./restIntakeSample";
import { sampleIntake } from "./workIntakeSetupApi";
import "../../../admin/components/restApis/restApis.css";

// The What and How panes of a Custom REST Work source (backend): the list operation and the role it reads as;
// the field mapping (dot paths), the status mapping, the write-back and the dry run. The drawer around them is shared
// with Jira and ServiceNow (`WorkIntakeSetupDrawer`).

type Update = (patch: Partial<IntakeDraft>) => void;
export type FieldErrors = Record<string, string>;

const formOf = (draft: IntakeDraft) => draft.rest ?? emptyRestForm();
const operationLabel = (operation: RestOperationInfo) => `${operation.name} · ${operation.method} ${operation.path}`;

// Shared with the Custom REST Knowledge source (Knowledge › Sources).
export function PairsEditor({ label, pairs, onChange, hint }: { label: string; pairs: Pair[]; onChange: (next: Pair[]) => void; hint?: string }) {
  const set = (index: number, patch: Partial<Pair>) => onChange(pairs.map((pair, at) => (at === index ? { ...pair, ...patch } : pair)));
  return (
    <div className="admin-panel__field rst-field" role="group" aria-label={label}>
      <span>{label}</span>
      {pairs.map((pair, index) => (
        <div key={index} className="work-intake__pair">
          <input className="admin-panel__input work-mono" aria-label={`${label}: name ${index + 1}`} placeholder="name" value={pair.name}
            onChange={(event) => set(index, { name: event.target.value })} />
          <input className="admin-panel__input work-mono" aria-label={`${label}: value ${index + 1}`} placeholder="value" value={pair.value}
            onChange={(event) => set(index, { value: event.target.value })} />
          <button type="button" className="admin-panel__action-btn" aria-label={`Remove ${pair.name || "row"}`}
            onClick={() => onChange(pairs.filter((_, at) => at !== index))}>Remove</button>
        </div>
      ))}
      <div><button type="button" className="admin-panel__action-btn" onClick={() => onChange([...pairs, { name: "", value: "" }])}>+ Add</button></div>
      {hint ? <small className="rst-hint">{hint}</small> : null}
    </div>
  );
}

export function RestWhatStep({ draft, found, update, errors }: {
  draft: IntakeDraft; found: IntakeDiscovery | null; update: Update; errors: FieldErrors;
}) {
  const form = formOf(draft);
  const set = (patch: Partial<RestSourceForm>) => update({ rest: { ...form, ...patch } });
  const operations = found?.list_operations ?? [];
  const operation = operations.find((entry) => entry.op_key === form.operation);
  const rule = roleRule(operation, form.role);
  if (!found) return <p className="admin-panel__hint">Reading the API's operations…</p>;
  return (
    <>
      <p className="admin-panel__hint">Items come from one read operation of <b>{found.name ?? draft.connection_id}</b>. Only its enabled read operations are offered.</p>
      <Field label="List operation" error={errors["what.operation"]} testId="rest-intake-operation"
        hint={operation ? [operation.summary, operation.paginated ? "Reads page by page." : ""].filter(Boolean).join(". ") || undefined : undefined}>
        <select className="admin-panel__input" value={form.operation} onChange={(event) => {
          const next = operations.find((entry) => entry.op_key === event.target.value);
          set({ operation: event.target.value, role: next && next.roles.length === 1 ? next.roles[0] : "" });
        }}>
          <option value="">Pick an operation</option>
          {operations.map((entry) => <option key={entry.op_key} value={entry.op_key}>{operationLabel(entry)}</option>)}
        </select>
      </Field>
      {!operations.length ? <p className="work-intake__muted">This API has no enabled read operation. Enable one in Connections › REST APIs.</p> : null}
      {operation ? (
        <>
          {rule.required ? (
            <div className="work-note" role="note" data-testid="rest-intake-role-required">
              <b>A role is required.</b> This operation's grants have a scope (for example a group or a customer). The sync
              reads as the role you pick, and its scope is enforced as that role, so the intake only sees what that role may see.
            </div>
          ) : null}
          <Field label="Read as role" error={errors["what.role"] ?? (form.role ? rule.problem : null)} testId="rest-intake-role"
            hint={rule.required ? "Required: the roles below hold a grant of this operation." : "Optional: without scoped grants the sync reads as a granted role."}>
            <select className="admin-panel__input" value={form.role} onChange={(event) => set({ role: event.target.value })}>
              <option value="">{rule.required ? "Pick a role" : "Any granted role"}</option>
              {rule.roles.map((role) => (
                <option key={role} value={role}>{operation.scoped_roles.includes(role) ? `${role} (scoped)` : role}</option>
              ))}
            </select>
          </Field>
          <PairsEditor label="Fixed arguments" pairs={form.arguments} onChange={(next) => set({ arguments: next })}
            hint="Sent with every call, for example state = open. The role's scope is added last and always wins." />
        </>
      ) : null}
    </>
  );
}

function FieldMapping({ form, set, errors }: { form: RestSourceForm; set: (patch: Partial<RestSourceForm>) => void; errors: FieldErrors }) {
  const problems = mappingProblems(form.fields);
  const row = (name: string) => {
    const touched = name in form.fields;
    const error = errors[`how.field_mapping.${name}`] ?? (touched ? problems[name] : undefined);
    return (
      <Field key={name} label={`${FIELD_LABELS[name] ?? name}${(REQUIRED_FIELDS as readonly string[]).includes(name) ? " *" : ""}`} error={error}>
        <input className="admin-panel__input work-mono" value={form.fields[name] ?? ""} placeholder={name === "key" ? "number" : name === "status" ? "state.name" : ""}
          onChange={(event) => set({ fields: { ...form.fields, [name]: event.target.value } })} />
      </Field>
    );
  };
  return (
    <section className="work-intake__section" aria-label="Field mapping" data-testid="rest-intake-mapping">
      <div className="admin-panel__section-header work-intake__subhead"><span>Field mapping</span></div>
      <p className="work-intake__muted">{DOT_PATH_HINT} Key, title and status are required.</p>
      {errors["how.field_mapping"] ? <p className="rst-field__error" role="alert">{errors["how.field_mapping"]}</p> : null}
      <div className="admin-panel__form-grid">{[...REQUIRED_FIELDS, "id", "description"].map(row)}</div>
      <details className="work-intake__adv"><summary>More fields</summary>
        <div className="admin-panel__form-grid">{OPTIONAL_FIELDS.filter((name) => name !== "id" && name !== "description").map(row)}</div>
        <p className="work-intake__muted">Reporter and assignee are kept only as identifiers (login, e-mail, id); a display name is dropped. Links must be http(s).</p>
      </details>
    </section>
  );
}

function StatusMapping({ form, set, states, errors }: {
  form: RestSourceForm; set: (patch: Partial<RestSourceForm>) => void; states: Array<{ key: string; label: string }>; errors: FieldErrors;
}) {
  const problems = statusRowProblems(form.statusRows);
  const setRow = (index: number, patch: Partial<RestSourceForm["statusRows"][number]>) =>
    set({ statusRows: form.statusRows.map((row, at) => (at === index ? { ...row, ...patch } : row)) });
  return (
    <section className="work-intake__section" aria-label="Status mapping" data-testid="rest-intake-status">
      <div className="admin-panel__section-header work-intake__subhead"><span>{neutralLabel("source_status")} → Octryx state</span></div>
      <p className="work-intake__muted">Matched without regard to case. A status that is not listed lands in Intake.</p>
      {errors["how.status_mapping"] ? <p className="rst-field__error" role="alert">{errors["how.status_mapping"]}</p> : null}
      {form.statusRows.length ? (
        <div className="work-intake__map">
          {form.statusRows.map((row, index) => (
            <div key={index}>
              <input className="admin-panel__input" aria-label={`${neutralLabel("source_status")} ${index + 1}`} value={row.status}
                placeholder="e.g. Working" onChange={(event) => setRow(index, { status: event.target.value })} />
              <span className="work-intake__arrow">→</span>
              <select className="admin-panel__input" aria-label={`Octryx state for ${row.status || `row ${index + 1}`}`} value={row.state}
                onChange={(event) => setRow(index, { state: event.target.value })}>
                <option value="">Pick a state</option>
                {states.map((state) => <option key={state.key} value={state.key}>{state.label}</option>)}
              </select>
              <button type="button" className="admin-panel__action-btn" onClick={() => set({ statusRows: form.statusRows.filter((_, at) => at !== index) })}>Remove</button>
              {problems[index] ? <small className="rst-field__error work-intake__row-error" role="alert">{problems[index]}</small> : null}
            </div>
          ))}
        </div>
      ) : null}
      <div><button type="button" className="admin-panel__action-btn" onClick={() => set({ statusRows: [...form.statusRows, { status: "", state: "" }] })}>+ Add status</button></div>
      <Field label="Closed statuses" error={errors["how.closed_statuses"]} hint="A record in one of these closes its Work item. Separate with commas.">
        <input className="admin-panel__input" value={form.closedStatuses.join(", ")} onChange={(event) => set({ closedStatuses: event.target.value.split(",").map((entry) => entry.trimStart()) })} />
      </Field>
    </section>
  );
}

function WriteBack({ form, set, operations, templateKeys, errors }: {
  form: RestSourceForm; set: (patch: Partial<RestSourceForm>) => void; operations: RestOperationInfo[]; templateKeys: string[];
  errors: FieldErrors;
}) {
  const body = parseBodyTemplate(form.writeBody);
  return (
    <section className="work-intake__section" aria-label="Write-back" data-testid="rest-intake-writeback">
      <div className="admin-panel__section-header work-intake__subhead"><span>Write-back</span></div>
      <Field label={neutralLabel("source_transition")} error={errors["how.write_back.operation"] ?? errors["how.write_back"]}
        hint="A write operation of the same API. Leave it empty to read only.">
        <select className="admin-panel__input" value={form.writeOperation} onChange={(event) => set({ writeOperation: event.target.value })}>
          <option value="">None: read only</option>
          {operations.map((entry) => <option key={entry.op_key} value={entry.op_key}>{operationLabel(entry)}</option>)}
        </select>
      </Field>
      {form.writeOperation ? (
        <>
          <PairsEditor label="Arguments" pairs={form.writeArguments} onChange={(next) => set({ writeArguments: next })}
            hint={`Placeholders: ${templateKeys.map((key) => `{${key}}`).join(", ")}. For example id = {source_key}.`} />
          <Field label="Body (JSON)" error={errors["how.write_back.body"] ?? body.problem}>
            <textarea className="admin-panel__textarea rst-code work-intake__template" rows={4} value={form.writeBody} placeholder={'{"status": "{target_status}"}'}
              onChange={(event) => set({ writeBody: event.target.value })} />
          </Field>
          <p className="work-intake__muted" data-testid="rest-intake-approval">
            Writes need an approval: a person's transition writes as that person, after they confirm its preview. A transition
            without a person (a run, a sync) only proposes the write. Which status each Octryx state writes is the workflow's
            “{neutralLabel("source_status")}”.
          </p>
        </>
      ) : null}
    </section>
  );
}

export function RestHowStep({ draft, found, workspaceId, update, errors }: {
  draft: IntakeDraft; found: IntakeDiscovery | null; workspaceId: string; update: Update; errors: FieldErrors;
}) {
  const form = formOf(draft);
  const set = (patch: Partial<RestSourceForm>) => update({ rest: { ...form, ...patch } });
  return (
    <>
      <FieldMapping form={form} set={set} errors={errors} />
      <StatusMapping form={form} set={set} states={found?.work_states ?? []} errors={errors} />
      <WriteBack form={form} set={set} operations={found?.write_operations ?? []} templateKeys={found?.template_keys ?? []}
        errors={errors} />
      <label className="admin-panel__checkbox" data-testid="rest-intake-auto-analyze">
        <input type="checkbox" checked={form.autoAnalyze} onChange={(event) => set({ autoAnalyze: event.target.checked })} />
        <span>Analyze new items automatically (only items that arrive in Intake; reporter questions are only proposed)</span>
      </label>
      <RestDryRun draft={draft} found={found} workspaceId={workspaceId} />
    </>
  );
}

function RestDryRun({ draft, found, workspaceId }: { draft: IntakeDraft; found: IntakeDiscovery | null; workspaceId: string }) {
  const [view, setView] = useState<SampleView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = JSON.stringify([draft.connection_id, draft.rest]);
  useEffect(() => { setView(null); setError(null); }, [key]);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setView(sampleView(await sampleIntake(workspaceId, draft), found?.work_states ?? []));
    } catch (failure) {
      setView(null);
      setError(refusalOf(failure).text);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="work-intake__section" aria-label="Dry run" data-testid="rest-intake-dry-run">
      <div className="admin-panel__section-header work-intake__subhead">
        <span>Dry run</span>
        <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => void run()}>{busy ? "Reading…" : "Run dry run"}</button>
      </div>
      <p className="work-intake__muted">Reads one page as the chosen role and maps it. Creates nothing and stores nothing; the call is audited.</p>
      {error ? <p className="rst-field__error" role="alert">{error}</p> : null}
      {view ? (
        <>
          <div className="work-intake__kv" data-testid="rest-intake-dry-run-facts">
            <div><b>Read</b>{view.read}{view.lastPage ? "" : " (first page)"}</div>
            <div><b>Would map</b>{view.mapped}</div>
            <div><b>Dropped</b>{view.dropped}{view.droppedReasons.length ? <span className="work-intake__muted">{view.droppedReasons.join(" · ")}</span> : null}</div>
            <div><b>Read as</b>{view.role || "–"}</div>
          </div>
          {view.rows.length ? (
            <table className="admin-panel__table work-cards">
              <thead><tr><th>Key</th><th>Title</th><th>Status</th><th>Becomes</th><th>Mapped fields</th></tr></thead>
              <tbody>
                {view.rows.map((row) => (
                  <tr key={row.key}>
                    <td data-label="Key" className="work-mono">{row.key}</td>
                    <td data-label="Title">{row.title}</td>
                    <td data-label="Status">{row.status || "–"}</td>
                    <td data-label="Becomes">{row.becomes}</td>
                    <td data-label="Mapped fields">{row.extra || "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="admin-panel__hint">No record of this page could be mapped.</p>}
          {view.closed ? <p className="work-intake__muted">{view.closed === 1 ? "1 record is" : `${view.closed} records are`} in a closed status and would close its Work item.</p> : null}
        </>
      ) : null}
    </section>
  );
}
