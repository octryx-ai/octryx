import { useCallback, useEffect, useState } from "react";

import { deleteTestCase, loadEntities, loadPickerEntities, loadTestCases, runTestBench, runTestCases, saveTestCase } from "./policyEngineApi";
import { benchRequest, readBenchResult, readEntities, readTestCases, resourceField } from "./policyEngineBench";
import { readTestReport, refusalText } from "./policyEngineVersions";
import type { BenchEntities, BenchForm, BenchResult, TestCase } from "./policyEngineBench";
import type { TestReport } from "./policyEngineVersions";
import { readPickerEntities } from "./policyCatalogModel";
import type { NamedConnection } from "./policyCatalogModel";
import { BenchAnswer, BenchCases, BenchQuestion } from "./AdminPolicyTestBenchParts";

const EMPTY: BenchForm = { workspaceId: "", userId: "", action: "use_seat", value: "", tool: "", params: "", connection: "" };
const SOURCES = [{ id: "published", label: "Published policies" }, { id: "draft", label: "Current draft" }];

// The bench's catalog (entities, connections, saved cases), the question, the answer and the busy/message state.
function usePolicyBench() {
  const [entities, setEntities] = useState<BenchEntities | null>(null);
  const [connections, setConnections] = useState<NamedConnection[]>([]);
  const [cases, setCases] = useState<TestCase[]>([]);
  const [form, setForm] = useState<BenchForm>(EMPTY);
  const [source, setSource] = useState("published");
  const [result, setResult] = useState<BenchResult | null>(null);
  const [report, setReport] = useState<TestReport | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const [rawEntities, rawCases] = await Promise.all([loadEntities(), loadTestCases()]);
      const read = readEntities(rawEntities);
      setEntities(read);
      setCases(readTestCases(rawCases));
      setForm((current) => (current.workspaceId ? current : { ...current, workspaceId: read.workspaces[0]?.id ?? "" }));
    } catch (error) {
      setMessage({ ok: false, text: refusalText(error) });
    }
  }, []);
  useEffect(() => {
    void load();
    void loadPickerEntities().then((raw) => setConnections(readPickerEntities(raw).namedConnections)).catch(() => setConnections([]));
  }, [load]);

  return {
    entities, connections, cases, form, setForm, source, setSource, result, setResult, report, setReport, name, setName,
    busy, setBusy, message, setMessage, load,
  };
}

type Bench = ReturnType<typeof usePolicyBench>;

// Ask the question, run a change and reload, or run every saved case; each is busy while it runs.
function benchActions(bench: Bench, request: ReturnType<typeof benchRequest>["request"]) {
  const { source, setResult, setReport, setBusy, setMessage, load } = bench;
  const withSource = (body: Record<string, unknown>) => (source === "draft" ? { ...body, source: "draft" } : body);
  const ask = async () => {
    if (!request) return;
    setBusy(true);
    setMessage(null);
    try {
      setResult(readBenchResult(await runTestBench(withSource(request))));
    } catch (error) {
      setMessage({ ok: false, text: refusalText(error) });
    } finally {
      setBusy(false);
    }
  };
  const act = async (action: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setMessage(null);
    try {
      await action();
      await load();
      setMessage({ ok: true, text: done });
    } catch (error) {
      setMessage({ ok: false, text: refusalText(error) });
    } finally {
      setBusy(false);
    }
  };
  const runAll = async () => {
    setBusy(true);
    try {
      setReport(readTestReport(await runTestCases(source === "draft" ? { source: "draft" } : {})));
    } catch (error) {
      setMessage({ ok: false, text: refusalText(error) });
    } finally {
      setBusy(false);
    }
  };
  return { ask, act, runAll };
}

// Policies → "Test bench": "May <principal> do <action> on <resource> in <Workspace>?" with real Workspaces,
// users, tools, connections and model aliases. The answer names the deciding policies and, next to it, what the
// existing check decides. A question can be saved as a test case with its expected answer; saved cases run on every
// draft save and block publishing when they fail.
export function AdminPolicyTestBench() {
  const bench = usePolicyBench();
  const { entities, connections, cases, form, setForm, source, setSource, result, setResult, report, name, setName, busy, message } = bench;

  if (!entities) return message ? <p className="workspace-classification__message" role="alert">{message.text}</p> : <p className="admin-panel__hint" role="status">Loading…</p>;

  const set = (patch: Partial<BenchForm>) => { setForm({ ...form, ...patch }); setResult(null); };
  const built = benchRequest(form);
  const field = resourceField(form.action);
  const { ask, act, runAll } = benchActions(bench, built.request);
  const denied = result?.decision === "deny";

  return (
    <div className="policies__pane" data-testid="policy-test-bench">
      <section className="admin-panel__card" aria-label="Test bench">
        <div className="admin-panel__section-header">
          <span>Ask the policies</span>
          <span className="work-badge work-badge--neutral">Against: {SOURCES.find((item) => item.id === source)?.label}</span>
        </div>
        <p className="admin-panel__hint">Ask Cedar about a real Workspace and user. Nothing is executed and nothing is recorded.</p>
        <BenchQuestion sources={SOURCES} source={source} setSource={setSource} field={field} form={form} set={set} entities={entities}
          connections={connections} />
        {built.problem ? <p className="admin-panel__hint" data-testid="bench-problem">{built.problem}</p> : null}
        <div className="policies__row">
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="bench-ask"
            disabled={busy || !built.request} onClick={() => void ask()}>Ask</button>
          {result ? (
            <>
              <span className={`work-badge ${denied ? "work-badge--danger" : "work-badge--active"}`} data-testid="bench-decision">{denied ? "Denied" : "Allowed"} — {result.principal} · {result.action} · {result.resource}</span>
              {result.legacy ? <span className="policies__summary" data-testid="bench-legacy">existing check: {result.legacy.decision}{result.legacy.reason ? ` (${result.legacy.reason})` : ""}</span> : null}
            </>
          ) : null}
        </div>
        {result ? (
          <BenchAnswer result={result} name={name} setName={setName} busy={busy} canSave={Boolean(built.request)}
            onSave={() => void act(() => saveTestCase({ name: name.trim(), expected: result.decision, request: built.request }), "Test case saved.")} />
        ) : null}
        {message ? <p className={message.ok ? "admin-panel__success" : "workspace-classification__message"} role={message.ok ? "status" : "alert"} data-testid="bench-message">{message.text}</p> : null}
      </section>
      <BenchCases cases={cases} report={report} busy={busy} onRunAll={() => void runAll()}
        onDelete={(item) => void act(() => deleteTestCase(item.id), "Test case deleted.")} />
    </div>
  );
}
