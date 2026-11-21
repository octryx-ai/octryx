// The parts of the policy test bench: the resource fields of an action, the answer with its deciding policies, and
// the saved test cases.
import { CedarCode } from "./CedarCode";
import { testCaseLabel } from "./policyEngineBench";
import type { BenchEntities, BenchForm, BenchResult, TestCase } from "./policyEngineBench";
import type { TestReport } from "./policyEngineVersions";
import { SOURCE_LABELS } from "./policyCatalogModel";
import type { NamedConnection } from "./policyCatalogModel";
import { PolicyRef } from "./PolicyRef";
import { PolicyTestReport } from "./PolicyTestReport";

type QuestionProps = {
  field: string | null;
  form: BenchForm;
  set: (patch: Partial<BenchForm>) => void;
  entities: BenchEntities;
  connections: NamedConnection[];
};

// The fields of the resource the chosen action asks about (model alias, data-policy class, tool, command or path).
function BenchResourceFields({ field, form, set, entities, connections }: QuestionProps) {
  return (
    <>
      {field === "alias" ? (
        <label className="admin-panel__field"><span>Model alias</span><input list="bench-aliases" value={form.value} data-testid="bench-value" onChange={(event) => set({ value: event.target.value })} />
          <datalist id="bench-aliases">{entities.modelAliases.map((item) => <option key={item} value={item} />)}</datalist></label>
      ) : field === "data_policy_class" ? (
        <label className="admin-panel__field"><span>Model data-policy class</span><select value={form.value} data-testid="bench-value" onChange={(event) => set({ value: event.target.value })}>
          <option value="">unknown</option>
          {entities.dataPolicyClasses.map((item) => <option key={item} value={item}>{item}</option>)}
        </select></label>
      ) : field === "tool" ? (
        <>
          <label className="admin-panel__field"><span>Tool</span><input list="bench-tools" value={form.tool} data-testid="bench-tool" onChange={(event) => set({ tool: event.target.value })} />
            <datalist id="bench-tools">{entities.tools.map((item) => <option key={item} value={item} />)}</datalist></label>
          <label className="admin-panel__field"><span>Connection</span><select value={form.connection ?? ""} data-testid="bench-connection" onChange={(event) => set({ connection: event.target.value })}>
            <option value="">Not on a named connection</option>
            <option value="default">default</option>
            {connections.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.connector} · {item.scope === "global" ? "Global" : item.workspaceName}</option>)}
          </select></label>
          <label className="admin-panel__field"><span>Arguments (JSON, optional)</span><input value={form.params} data-testid="bench-params" placeholder='{"args": "get pods"}' onChange={(event) => set({ params: event.target.value })} /></label>
        </>
      ) : field === "command" ? (
        <label className="admin-panel__field"><span>Command</span><input value={form.value} data-testid="bench-value" placeholder="kubectl --context <cluster> rollout restart deploy/<name>" onChange={(event) => set({ value: event.target.value })} /></label>
      ) : field === "path" ? (
        <>
          <label className="admin-panel__field"><span>Path</span><input value={form.value} data-testid="bench-value" onChange={(event) => set({ value: event.target.value })} /></label>
          <label className="admin-panel__field"><span>Client tool</span><input value={form.tool} data-testid="bench-tool" placeholder={form.action === "write_path" ? "Edit" : "Read"} onChange={(event) => set({ tool: event.target.value })} /></label>
        </>
      ) : null}
    </>
  );
}

// Which policies, who, which Workspace, which action, and the resource fields of that action.
export function BenchQuestion({ sources, source, setSource, ...props }: QuestionProps & {
  sources: { id: string; label: string }[];
  source: string;
  setSource: (source: string) => void;
}) {
  const { form, set, entities } = props;
  return (
    <div className="admin-panel__form-grid">
      <label className="admin-panel__field"><span>Policies</span><select value={source} data-testid="bench-source" onChange={(event) => setSource(event.target.value)}>
        {sources.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select></label>
      <label className="admin-panel__field"><span>Who</span><select value={form.userId} data-testid="bench-user" onChange={(event) => set({ userId: event.target.value })}>
        <option value="">No user (system)</option>
        {entities.users.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></label>
      <label className="admin-panel__field"><span>Workspace</span><select value={form.workspaceId} data-testid="bench-workspace" onChange={(event) => set({ workspaceId: event.target.value })}>
        {entities.workspaces.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.classification || "unclassified"}</option>)}
      </select></label>
      <label className="admin-panel__field"><span>Action</span><select value={form.action} data-testid="bench-action" onChange={(event) => set({ action: event.target.value, value: "", tool: "", connection: "" })}>
        {entities.actions.map((item) => <option key={item} value={item}>{item}</option>)}
      </select></label>
      <BenchResourceFields {...props} />
    </div>
  );
}

// The deciding policies, notes and errors of the last answer, and saving the question as a test case.
export function BenchAnswer({ result, name, setName, busy, canSave, onSave }: {
  result: BenchResult;
  name: string;
  setName: (name: string) => void;
  busy: boolean;
  canSave: boolean;
  onSave: () => void;
}) {
  return (
    <div className="policies__pane" data-testid="bench-result">
      {result.notes.map((note) => <div key={note} className="policies__warn" data-testid="bench-note">{note}</div>)}
      {result.errors.length ? <p className="workspace-classification__message">Errors (denied): {result.errors.join("; ")}</p> : null}
      <ul className="policies__summary" data-testid="bench-determining">
        {result.determining.length ? result.determining.map((item) => (
          <li key={item.id}><PolicyRef id={item.id} className="policies__ref" /> <span className="work-badge work-badge--neutral">{item.source === "custom" ? "Custom policy" : SOURCE_LABELS[item.source] ?? item.source}</span>{item.text ? <CedarCode text={item.text} /> : null}</li>
        )) : <li>No policy matched: Cedar's default is deny.</li>}
      </ul>
      <div className="policies__row">
        <input className="policies__input-inline" value={name} placeholder="Test case name" maxLength={120} data-testid="bench-case-name" onChange={(event) => setName(event.target.value)} />
        <button type="button" className="admin-panel__action-btn" data-testid="bench-save-case" disabled={busy || !name.trim() || !canSave}
          onClick={onSave}>
          Save as test case (expect {result.decision})
        </button>
      </div>
    </div>
  );
}

export function BenchCases({ cases, report, busy, onRunAll, onDelete }: {
  cases: TestCase[];
  report: TestReport | null;
  busy: boolean;
  onRunAll: () => void;
  onDelete: (item: TestCase) => void;
}) {
  return (
    <section className="admin-panel__card" aria-label="Saved test cases" data-testid="bench-cases">
      <div className="admin-panel__section-header">
        <span>Saved test cases ({cases.length})</span>
        <button type="button" className="admin-panel__action-btn" data-testid="bench-run-all" disabled={busy || !cases.length} onClick={onRunAll}>Run all</button>
      </div>
      <p className="admin-panel__hint">Saved cases run on every draft save and again at publish; a failing case blocks publishing.</p>
      <table className="admin-panel__table">
        <tbody>
          {cases.map((item) => (
            <tr key={item.id} data-testid="bench-case">
              <td className="policies__name">{item.name}</td>
              <td className="policies__summary">{testCaseLabel(item)}</td>
              <td><button type="button" className="admin-users__row-btn" data-testid={`bench-delete-${item.id}`} disabled={busy}
                onClick={() => onDelete(item)}>Delete</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {report ? <PolicyTestReport report={report} /> : null}
    </section>
  );
}
