import { useCallback, useEffect, useState, type CSSProperties } from "react";

import { useAdminNavigation } from "../../adminNavigation";
import { readJson } from "../../utils/adminPanelHelpers";
import { AdminDetectors } from "../policyEngine/AdminDetectors";
import { LevelTag, SubTabs } from "../settingsKit/SettingsKit";
import "../settingsKit/settingsKit.css";
import type { ContentSecurity } from "./contentSecurityModel";
import { CATEGORY_TEXT, readContentSecurity } from "./contentSecurityModel";

const PATH = "/api/v1/admin/content-security";
type Tab = "overview" | "detectors" | "models";
const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" }, { id: "detectors", label: "Detectors" }, { id: "models", label: "Approved models" },
];
const LEGEND: [string, string][] = [["refuse", "Refuse"], ["mask", "Mask / reroute"], ["report", "Allow (recorded)"], ["none", "Not scanned"]];

// Settings → Security → "Content security": what is detected, what is decided, what happens —
// the coverage per surface and category, the one detector library (edited here, stored in the policy set) and the
// approved models (read-only).
export function ContentSecurityPage() {
  const { openAdminTab } = useAdminNavigation();
  const [data, setData] = useState<ContentSecurity | null>(null);
  const [workspaces, setWorkspaces] = useState<{ id: string; name: string }[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => loadOverview(setData, setProblem), []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (tab !== "detectors") return;
    readJson<{ workspaces?: { id: string; name: string }[] }>("/api/v1/admin/policy-engine/entities")
      .then((answer) => setWorkspaces(Array.isArray(answer?.workspaces) ? answer.workspaces : []))
      .catch(() => setWorkspaces([]));
  }, [tab]);

  if (problem) return <p className="sk-err" role="alert">{problem}</p>;
  if (!data) return <p className="sk-hint" role="status">Loading content security…</p>;

  return (
    <div className="sk-page" data-testid="content-security">
      <SubTabs value={tab} tabs={TABS} onChange={setTab} label="Content security" />
      {message ? <p className={message.ok ? "admin-panel__success" : "sk-err"} role={message.ok ? "status" : "alert"}>{message.text}</p> : null}
      {tab === "overview" ? <OverviewTab data={data} onTab={setTab} onOpenPolicies={() => openAdminTab("cedarPolicies")} /> : null}
      {tab === "detectors" ? (
        <AdminDetectors target={data.editTarget} workspaces={workspaces}
          onSaved={async (text) => { await load(); setMessage({ ok: true, text }); }} />
      ) : null}
      {tab === "models" ? <ModelsTab data={data} /> : null}
    </div>
  );
}

type SetState<T> = (value: T) => void;

async function loadOverview(setData: SetState<ContentSecurity | null>, setProblem: SetState<string | null>) {
  try {
    setData(readContentSecurity(await readJson<unknown>(PATH)));
  } catch (error) {
    setProblem((error as { status?: number }).status === 403 ? "Only platform admins can see content security." : "Content security could not be loaded.");
  }
}

function OverviewTab({ data, onTab, onOpenPolicies }: { data: ContentSecurity; onTab: (tab: Tab) => void; onOpenPolicies: () => void }) {
  const coverage = data.coverage;
  return (
    <>
      <div className="sk-pipe">
        <section className="admin-panel__card">
          <span className="sk-pipe__n">1 · Detect</span>
          <h4>{coverage.detectors} detectors</h4>
          <p className="sk-hint">{coverage.customDetectors} custom.</p>
          <button type="button" className="sk-link" onClick={() => onTab("detectors")}>Detectors</button>
        </section>
        <section className="admin-panel__card">
          <span className="sk-pipe__n">2 · Decide</span>
          <h4>{coverage.contentPolicies} content {coverage.contentPolicies === 1 ? "policy" : "policies"}</h4>
          <p className="sk-hint">
            {coverage.publishedVersion ? `Published in Policies, version ${coverage.publishedVersion}.` : "No policy set is published yet."}{" "}
            Each says block, mask or reroute per category.
          </p>
          <p className="sk-hint" data-testid="content-platform-policies">
            Always enforced on every model call, every driver: {coverage.platformPolicies.map((item) => item.label).join(" · ") || "none"}.
          </p>
          <button type="button" className="sk-link" onClick={onOpenPolicies}>Open Policies</button>
        </section>
        <section className="admin-panel__card">
          <span className="sk-pipe__n">3 · Act</span>
          <h4>{data.approvedModels.filter((model) => model.approvedFor.length).length} approved models</h4>
          <p className="sk-hint">Reroute targets for sensitive data. Classification limits which levels may use them.</p>
          <button type="button" className="sk-link" onClick={() => onTab("models")}>Approved models</button>
        </section>
      </div>
      <section className="admin-panel__card" aria-label="Coverage">
        <div className="admin-panel__section-header">
          <span>Coverage — what happens where</span>
          <span className="sk-muted">from the published policies{coverage.mode !== "enforce" ? " · the policy engine is in shadow" : ""}</span>
        </div>
        <div className="sk-cov" data-testid="content-coverage" style={{ "--sk-cov-columns": coverage.categories.length } as CSSProperties}>
          <div className="h">Where</div>
          {coverage.categories.map((category) => <div key={category.id} className="h">{CATEGORY_TEXT[category.id] ?? category.label}</div>)}
          {coverage.rows.map((row) => (
            <div key={row.key} className="sk-cov__row">
              <div className="s">{row.label}<small>{row.sub}</small></div>
              {row.cells.map((cell) => (
                <div key={cell.category} data-cat={CATEGORY_TEXT[cell.category] ?? cell.category}>
                  <span className={`sk-out sk-out--${cell.tone}`}>{cell.text}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
        <div className="sk-chips">{LEGEND.map(([tone, label]) => <span key={tone} className={`sk-out sk-out--${tone}`}>{label}</span>)}</div>
      </section>
    </>
  );
}

function ModelsTab({ data }: { data: ContentSecurity }) {
  const levelOf = (key: string) => data.levels.find((level) => level.key === key);
  return (
    <div className="sk-page">
      <table className="admin-panel__table sk-cards" data-testid="content-models">
        <thead><tr><th>Model</th><th>Cleared up to</th><th>Approved for</th><th>Levels that may use it</th></tr></thead>
        <tbody>
          {data.approvedModels.length === 0 ? <tr><td colSpan={4} className="admin-panel__cell--muted">No company-gateway model.</td></tr> : null}
          {data.approvedModels.map((model) => {
            const cleared = levelOf(model.clearedUpTo);
            return (
              <tr key={model.alias}>
                <td data-label="Model"><div className="sk-name">{model.alias}</div><div className="sk-sub">Company gateway</div></td>
                <td data-label="Cleared up to">{cleared ? <LevelTag label={cleared.label} color={cleared.color} /> : model.clearedUpTo}</td>
                <td data-label="Approved for">
                  {model.approvedFor.length ? <span className="sk-chips">{model.approvedFor.map((item) => <span key={item} className="admin-policy-chip">{CATEGORY_TEXT[item] ?? item}</span>)}</span>
                    : <span className="admin-panel__cell--muted">–</span>}
                </td>
                <td data-label="Levels">{model.levels.map((key) => levelOf(key)?.label ?? key).join(", ") || "–"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
