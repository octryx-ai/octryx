// The parts of Observability → Usage & costs: the pricing warning, the tiles and the four tables.
import type { AdminNavigation } from "../../adminNavigation";
import { Badge } from "./obUi";
import { formatCount, formatMoney } from "./obFormat";
import { percent, unpricedModels, unpricedShare, type UsagePayload } from "./usageModel";

type OpenTab = AdminNavigation["openAdminTab"];

function Meter({ value }: { value: number | null }) {
  if (value === null) return null;
  return (
    <div className={`ob-meter ${value >= 80 ? "ob-meter--warn" : ""}`} role="meter" aria-valuenow={value}
      aria-valuemin={0} aria-valuemax={100} aria-label={`${value} % used`}>
      <span style={{ width: `${Math.min(100, value)}%` }} />
    </div>
  );
}

// Platform-billed tokens without a price: which models, what that means for caps, and where to set a price.
export function UsagePricingWarning({ data, openAdminTab }: { data: UsagePayload; openAdminTab: OpenTab }) {
  const missing = unpricedModels(data.by_model);
  const share = data.tiles ? unpricedShare(data.tiles) : 0;
  return (
    <div className="ob-warn" data-testid="usage-pricing-warning">
      {percent(share)} of platform-billed tokens in this window have <b>no price</b> (
      {missing.map((row, index) => (
        <span key={`${row.provider}-${row.model}`}>
          {index ? ", " : ""}<span className="admin-policy-inline-code">{row.model}</span>
        </span>
      ))}
      ). They count as $0 here, so the real spend is higher.{" "}
      {data.unpriced_policy === "block"
        ? "While a cost cap is active, new runs on an unpriced model are refused until it has a price."
        : "Cost caps cannot stop them."}{" "}
      <button type="button" className="ob-link" onClick={() => openAdminTab("providers")}>
        Set a price in Runtime → Providers
      </button>
    </div>
  );
}

export function UsageTiles({ tiles }: { tiles: UsagePayload["tiles"] }) {
  return (
    <div className="ob-tiles">
      <div className="ob-tile"><b>Spend (priced)</b><strong>{formatMoney(tiles.spend)}</strong><span>platform-billed models with a price</span></div>
      <div className="ob-tile">
        <b>Priced coverage</b><strong>{percent(tiles.priced_coverage)}</strong>
        <span>
          {tiles.priced_coverage !== null && tiles.priced_coverage < 1
            ? <Badge tone="attention">! below 100 %</Badge> : null} of platform-billed tokens
        </span>
      </div>
      <div className="ob-tile"><b>Tokens</b><strong>{formatCount(tiles.tokens)}</strong><span>incl. {formatCount(tiles.cache_tokens)} cached</span></div>
      <div className="ob-tile"><b>Active users</b><strong>{formatCount(tiles.active_users)}</strong><span>with at least one model call</span></div>
    </div>
  );
}

export function UsageByModel({ data, openAdminTab }: { data: UsagePayload; openAdminTab: OpenTab }) {
  return (
    <div className="admin-panel__card">
      <div className="admin-panel__section-header"><span>By model</span></div>
      <table className="admin-panel__table ob-cards">
        <thead><tr><th>Model</th><th className="ob-num">Tokens</th><th className="ob-num">Cost</th><th>Pricing</th></tr></thead>
        <tbody>
          {data.by_model.map((row) => (
            <tr key={`${row.provider}-${row.model}`}>
              <td data-label="Model"><div>{row.model || "unknown"}</div><div className="ob-sub">{row.provider}</div></td>
              <td data-label="Tokens" className="ob-num">{formatCount(row.tokens)}</td>
              <td data-label="Cost" className="ob-num">{row.pricing === "unpriced" ? "–" : formatMoney(row.cost)}</td>
              <td data-label="Pricing">
                {row.pricing === "unpriced" ? (
                  <span className="ob-row"><Badge tone="attention">! no price</Badge>
                    <button type="button" className="ob-link" onClick={() => openAdminTab("providers")}>Set</button></span>
                ) : row.pricing === "not_billed" ? <Badge tone="neutral">seat · not billed</Badge> : <Badge tone="active">✓ priced</Badge>}
              </td>
            </tr>
          ))}
          {!data.by_model.length ? <tr><td colSpan={4} className="admin-panel__cell--muted">No model calls in this window.</td></tr> : null}
        </tbody>
      </table>
    </div>
  );
}

export function UsageByWorkspace({ data }: { data: UsagePayload }) {
  return (
    <div className="admin-panel__card">
      <div className="admin-panel__section-header"><span>By Workspace</span></div>
      <table className="admin-panel__table ob-cards">
        <thead><tr><th>Workspace</th><th className="ob-num">Runs</th><th className="ob-num">Cost</th><th>Budget</th></tr></thead>
        <tbody>
          {data.by_workspace.map((row) => (
            <tr key={row.workspace_id ?? "none"}>
              <td data-label="Workspace">{row.workspace_name ?? "No Workspace"}</td>
              <td data-label="Runs" className="ob-num">{formatCount(row.runs)}</td>
              <td data-label="Cost" className="ob-num">{formatMoney(row.cost)}</td>
              <td data-label="Budget">
                {row.budget ? (
                  <><Meter value={row.budget.percent} />
                    <div className="ob-sub">{row.budget.percent ?? "–"} % of {formatMoney(row.budget.limit)} / month</div></>
                ) : <span className="ob-muted">no budget</span>}
              </td>
            </tr>
          ))}
          {!data.by_workspace.length ? <tr><td colSpan={4} className="admin-panel__cell--muted">No usage in this window.</td></tr> : null}
        </tbody>
      </table>
    </div>
  );
}

export function UsageByUser({ data }: { data: UsagePayload }) {
  return (
    <div className="admin-panel__card">
      <div className="admin-panel__section-header"><span>By user (top 5)</span></div>
      <table className="admin-panel__table ob-cards">
        <thead><tr><th>User</th><th className="ob-num">Runs</th><th className="ob-num">Cost</th></tr></thead>
        <tbody>
          {data.by_user.map((row) => (
            <tr key={row.user_id}>
              <td data-label="User">{row.user_name}</td>
              <td data-label="Runs" className="ob-num">{formatCount(row.runs)}</td>
              <td data-label="Cost" className="ob-num">{formatMoney(row.cost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function UsageBudgets({ data, openAdminTab }: { data: UsagePayload; openAdminTab: OpenTab }) {
  return (
    <div className="admin-panel__card">
      <div className="admin-panel__section-header">
        <span>Limits &amp; budgets</span>
        <button type="button" className="ob-link" onClick={() => openAdminTab("runtimeLimits")}>Edit in Models › Budgets</button>
      </div>
      <table className="admin-panel__table ob-cards">
        <thead><tr><th>Limit</th><th>Scope</th><th className="ob-num">Cap</th><th>Used</th></tr></thead>
        <tbody>
          {data.budgets.map((row) => (
            <tr key={`${row.limit}-${row.scope}`}>
              <td data-label="Limit">{row.limit}</td>
              <td data-label="Scope">{row.scope}</td>
              <td data-label="Cap" className="ob-num">{row.cap ? formatMoney(row.cap) : "off"}</td>
              <td data-label="Used">
                <Meter value={row.percent} />
                <div className="ob-sub">{row.limit === "Monthly" ? formatMoney(row.used) : `highest in window ${formatMoney(row.used)}`}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
