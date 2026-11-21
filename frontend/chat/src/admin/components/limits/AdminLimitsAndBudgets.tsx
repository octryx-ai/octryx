import { BudgetDrawer } from "./BudgetDrawer";
import "../modelCatalog/modelCatalog.css";
import {
  GATEWAY_DAILY,
  LIMIT_ROWS,
  UNIT_SUFFIX,
  atLimitText,
  isNoLimit,
  overrideCount,
  periodLabel,
  usd,
  usedText,
} from "./limitsContract";
import type { LimitRow } from "./limitsContract";
import { UnpricedModelPolicyField } from "./UnpricedModelPolicyField";
import { useLimitsAndBudgets, type LimitsPage } from "./useLimitsAndBudgets";
import { WorkflowRunCeilingField } from "./WorkflowRunCeilingField";
import { WorkspaceCostOverrides } from "./WorkspaceCostOverrides";
import "./limits.css";
import { EmptyLine } from "../../../layout/EmptyLine";
import { LoadingState } from "../../../layout/LoadingState";

type PageProps = { page: LimitsPage };

// Runtime → Execution → Limits & budgets: every limit in one table with its
// source and Workspace overrides, the budget periods, and the Workspace cost-cap overrides. Saves only its own keys.
export function AdminLimitsAndBudgets() {
  const page = useLimitsAndBudgets();
  const { stored, overview, message, saving, budget, setBudget, reloadOverview, save } = page;

  return (
    <div className="model-catalog" data-testid="limits-and-budgets">
      {!stored && !message ? <LoadingState label="the limits" variant="page" /> : null}
      {stored ? <LimitsTable page={page} /> : null}
      <OverridesList page={page} />
      {stored ? (
        <details className="admin-panel__card">
          <summary className="model-catalog__name">Technical limits</summary>
          <table className="admin-panel__table model-catalog__table limits__table">
            <thead><tr><th>Limit</th><th>Platform value</th><th>Source</th><th>Workspace overrides</th><th>Applies to</th></tr></thead>
            <tbody>{LIMIT_ROWS.filter((limit) => limit.technical).map((limit) => <LimitTableRow key={limit.key} page={page} limit={limit} />)}</tbody>
          </table>
        </details>
      ) : null}
      <BudgetPeriods page={page} />
      {overview ? <WorkspaceCostOverrides workspaces={overview.workspaces} onSaved={reloadOverview} /> : null}
      <UnpricedModelPolicyField />
      <WorkflowRunCeilingField />
      {message ? (
        <p className={message.error ? "admin-panel__error" : "admin-panel__success"} role={message.error ? "alert" : "status"}>
          {message.text}
        </p>
      ) : null}
      <div className="model-catalog__row-group">
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="limits-save"
          disabled={saving || !stored} onClick={() => void save()}>
          {saving ? "Saving…" : "Save limits"}
        </button>
      </div>
      {budget && overview ? (
        <BudgetDrawer budget={budget === "new" ? null : budget} overview={overview} onClose={() => setBudget(null)}
          onSaved={() => { setBudget(null); reloadOverview(); }} />
      ) : null}
    </div>
  );
}

function LimitTableRow({ page, limit }: PageProps & { limit: LimitRow }) {
  const { drafts, setDrafts, overview, stored } = page;
  const draft = drafts[limit.key] ?? "";
  const count = overrideCount(overview, limit.key);
  return (
    <tr>
      <td data-label="Limit"><b>{limit.label}</b></td>
      <td data-label="Platform value">
        <div className="limits__value">
          <input className="admin-users__toolbar-input limits__input" inputMode="decimal" aria-label={limit.label}
            value={isNoLimit(limit, draft) ? "" : draft} disabled={isNoLimit(limit, draft)}
            data-testid={`limit-${limit.key}`}
            onChange={(event) => setDrafts((current) => ({ ...current, [limit.key]: event.target.value }))} />
          <span className="model-catalog__sub">{UNIT_SUFFIX[limit.unit]}</span>
          {limit.costCap ? (
            <label className="admin-panel__checkbox">
              <input type="checkbox" checked={isNoLimit(limit, draft)}
                onChange={(event) => setDrafts((current) => ({
                  ...current, [limit.key]: event.target.checked ? "0" : (stored?.[limit.key] === "0" ? "" : stored?.[limit.key] ?? ""),
                }))} />
              No limit
            </label>
          ) : null}
        </div>
      </td>
      <td data-label="Source"><span className="limits__src">Platform</span></td>
      <td data-label="Workspace overrides"><OverridesCell page={page} limitKey={limit.key} count={count} /></td>
      <td data-label="Applies to" className="limits__muted">{limit.appliesTo}</td>
    </tr>
  );
}

function OverridesCell({ page: { openOverrides, setOpenOverrides }, limitKey: key, count }: PageProps & { limitKey: string; count: number }) {
  return count ? (
    <button type="button" className="admin-panel__action-btn" aria-expanded={openOverrides === key}
      onClick={() => setOpenOverrides((current) => (current === key ? "" : key))}>
      {count} {count === 1 ? "Workspace" : "Workspaces"}
    </button>
  ) : <span className="model-catalog__off">—</span>;
}

function LimitsTable({ page }: PageProps) {
  const { overview } = page;
  return (
    <table className="admin-panel__table model-catalog__table limits__table">
      <thead><tr><th>Limit</th><th>Platform value</th><th>Source</th><th>Workspace overrides</th><th>Applies to</th></tr></thead>
      <tbody>
        {LIMIT_ROWS.filter((limit) => !limit.technical).map((limit) => <LimitTableRow key={limit.key} page={page} limit={limit} />)}
        <tr>
          <td data-label="Limit"><b>Claude Code per person per day</b></td>
          <td data-label="Platform value">
            <span className="model-catalog__sub">Baseline {usd(String(overview?.gatewayBaseline ?? ""))} where a Workspace sets none</span>
          </td>
          <td data-label="Source"><span className="limits__src">Workspace only</span></td>
          <td data-label="Workspace overrides"><OverridesCell page={page} limitKey={GATEWAY_DAILY} count={overrideCount(overview, GATEWAY_DAILY)} /></td>
          <td data-label="Applies to" className="limits__muted">Claude Code</td>
        </tr>
        {overview?.environment.map((limit) => (
          <tr key={limit.key}>
            <td data-label="Limit"><b>{limit.label}</b></td>
            <td data-label="Platform value">{limit.value || "—"}</td>
            <td data-label="Source"><span className="limits__src">Environment (read-only)</span></td>
            <td data-label="Workspace overrides"><span className="model-catalog__off">—</span></td>
            <td data-label="Applies to" className="limits__muted">All API calls</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function OverridesList({ page: { openOverrides, overview } }: PageProps) {
  const overrideList = openOverrides && overview ? overview.overrides[openOverrides] ?? [] : [];
  return (
    <>
    {overrideList.length ? (
      <div className="admin-panel__card" data-testid="limit-overrides">
        <div className="admin-panel__section-header"><span>Workspace overrides</span></div>
        <ul className="limits__list">
          {overrideList.map((item) => (
            <li key={item.workspaceId}>
              {item.name}: {item.value === "0" ? "no limit (explicit)" : usd(item.value)}
            </li>
          ))}
        </ul>
      </div>
    ) : null}
    </>
  );
}

function BudgetPeriods({ page: { overview, setBudget } }: PageProps) {
  return (
    <div className="admin-panel__card">
      <div className="model-catalog__bar">
        <div className="admin-panel__section-header"><span>Budget periods</span></div>
        <button type="button" className="admin-panel__action-btn" data-testid="budget-add" onClick={() => setBudget("new")}>
          Add budget
        </button>
      </div>
      {overview?.budgets.length ? (
        <table className="admin-panel__table model-catalog__table" data-testid="budget-table">
          <thead><tr><th>Scope</th><th>Period</th><th>Amount</th><th>Used</th><th>At limit</th></tr></thead>
          <tbody>
            {overview.budgets.map((item) => (
              <tr key={item.id} className={item.active ? "" : "admin-panel__row--inactive"} tabIndex={0}
                onClick={() => setBudget(item)} onKeyDown={(event) => { if (event.key === "Enter") setBudget(item); }}>
                <td data-label="Scope">{item.scopeLabel}{item.active ? "" : " (off)"}</td>
                <td data-label="Period">{periodLabel(item.period)}</td>
                <td data-label="Amount">{usd(item.amount)}</td>
                <td data-label="Used">{usedText(item)}</td>
                <td data-label="At limit">
                  <span className={`work-badge work-badge--${item.stopAt <= 100 ? "danger" : "attention"}`}>{atLimitText(item)}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <EmptyLine text="No budget period is set." action={{ label: "Add budget", onClick: () => setBudget("new") }} testId="budget-empty" />}
    </div>
  );
}
