import { useEffect, useState } from "react";

import { loadUsage } from "./skillCatalogApi";
import { refusalText, usageSplit } from "./skillCatalogModel";
import type { SkillRow } from "./skillCatalogTypes";
import type { UsageSummary } from "./skillDeliveryTypes";
import { DAY_CHOICES, serverTime, usageKpis } from "./skillTabsModel";

// Skills → Usage: simple counts over a period. Skill loads split by
// surface (platform chat, octryx-claude model / slash), refusals by policy, and names used in octryx-claude sessions
// that are not catalog skills. Only the skill name, version digest, Workspace and session are recorded.
export function SkillUsageTab({ rows, onOpenSkill }: {
  rows: SkillRow[];
  onOpenSkill: (skillId: string, sub?: "usage") => void;
}) {
  const [days, setDays] = useState(30);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setProblem(null);
    loadUsage(days)
      .then((raw) => { if (alive) setUsage(raw as UsageSummary); })
      .catch((error) => { if (alive) setProblem(refusalText(error)); });
    return () => { alive = false; };
  }, [days]);

  const kinds = new Map(rows.map((row) => [row.id, row.kind]));
  const kpis = usage ? usageKpis(usage, rows) : null;

  return (
    <div data-testid="skills-usage">
      <div className="policies__flex-between" style={{ marginBottom: ".7rem" }}>
        <p className="admin-panel__hint">How often catalog skills were loaded, per surface. Searches are not counted as uses.</p>
        <label className="admin-panel__field"><span>Period</span>
          <select value={days} onChange={(event) => setDays(Number(event.target.value))} data-testid="usage-days">
            {DAY_CHOICES.map((value) => <option key={value} value={value}>Last {value} days</option>)}
          </select></label>
      </div>
      {problem ? <p className="workspace-classification__message" role="alert" data-testid="usage-problem">{problem}</p> : null}
      {!usage && !problem ? <p className="admin-panel__hint" role="status">Loading the usage…</p> : null}
      {usage && kpis ? (
        <>
          <UsageKpis usage={usage} kpis={kpis} />
          <UsageTable usage={usage} kinds={kinds} onOpenSkill={onOpenSkill} />
          <UnmanagedUsage usage={usage} />
        </>
      ) : null}
      <p className="skills__hint" style={{ marginTop: ".6rem" }}>octryx-claude reports a skill when the model calls the Skill tool
        (PreToolUse) or the user types <span className="admin-policy-inline-code">/octryx:&lt;skill&gt;</span> (UserPromptExpansion).
        Only the skill name, version digest, Workspace and session are recorded, never the prompt.</p>
    </div>
  );
}

function UsageKpis({ usage, kpis }: { usage: UsageSummary; kpis: ReturnType<typeof usageKpis> }) {
  return (
    <div className="policies__kpis" style={{ marginBottom: ".9rem" }}>
      <div className="policies__kpi" data-testid="usage-kpi-loads">
        <div className="policies__kpi-label">Skill loads · {usage.days} days</div>
        <div className="policies__kpi-value">{usage.totals.uses}</div>
        <div className="policies__kpi-meta">chat {kpis.chat} · octryx-claude {kpis.octryx}</div>
      </div>
      <div className="policies__kpi" data-testid="usage-kpi-in-use">
        <div className="policies__kpi-label">Skills in use</div>
        <div className="policies__kpi-value">{kpis.inUse} / {kpis.published}</div>
        <div className="policies__kpi-meta">{kpis.unused} published {kpis.unused === 1 ? "entry" : "entries"} unused for {usage.days} days</div>
      </div>
      <div className="policies__kpi" data-testid="usage-kpi-refused">
        <div className="policies__kpi-label">Refused by policy</div>
        <div className="policies__kpi-value">{usage.totals.refusals}</div>
        <div className="policies__kpi-meta">skill not assigned or a tool denied after load</div>
      </div>
    </div>
  );
}

// Loads per catalog skill and surface; a row opens the skill's usage.
function UsageTable({ usage, kinds, onOpenSkill }: {
  usage: UsageSummary;
  kinds: Map<string, string>;
  onOpenSkill: (skillId: string, sub?: "usage") => void;
}) {
  const dash = (value: number) => (value ? value : <span className="admin-panel__cell--muted">—</span>);
  return (
    <div className="skills__scroll">
      <table className="admin-panel__table">
        <thead><tr><th>Skill</th><th>Platform chat</th><th>octryx-claude (model / slash)</th><th>Last used</th></tr></thead>
        <tbody>
          {usage.skills.length ? usage.skills.map((entry) => {
            const split = usageSplit(entry.by_surface);
            return (
              <tr key={entry.skill_id} className="policies__table-row" data-testid={`usage-row-${entry.name}`} tabIndex={0}
                onClick={() => onOpenSkill(entry.skill_id, "usage")}
                onKeyDown={(event) => { if (event.key === "Enter") onOpenSkill(entry.skill_id, "usage"); }}>
                <td className="skills__mono">{entry.name}{kinds.get(entry.skill_id) === "mcp_server" ? <> <span className="skills__kind">MCP</span></> : null}</td>
                <td>{dash(split.chat)}</td>
                <td>{split.model || split.slash ? `${split.model} / ${split.slash}` : <span className="admin-panel__cell--muted">—</span>}</td>
                <td className="admin-panel__cell--muted">{serverTime(entry.last_used_at)}</td>
              </tr>
            );
          }) : (
            <tr><td colSpan={4}><div className="admin-panel__empty-state">No catalog skill was used in this period.</div></td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// Names used in octryx-claude sessions that are not catalog skills.
function UnmanagedUsage({ usage }: { usage: UsageSummary }) {
  return usage.unmanaged.length ? (
    <div className="admin-panel__card" style={{ marginTop: ".9rem" }} data-testid="usage-unmanaged">
      <div className="admin-panel__section-header">Not from the catalog (unmanaged)</div>
      <table className="admin-panel__table">
        <thead><tr><th>Skill name</th><th>Uses</th></tr></thead>
        <tbody>
          {usage.unmanaged.map((item) => (
            <tr key={item.name}><td className="skills__mono">{item.name}</td><td>{item.uses}</td></tr>
          ))}
        </tbody>
      </table>
      <p className="skills__hint">Project skills of octryx-claude sessions (a repository&apos;s own skills) are recorded by name only.</p>
    </div>
  ) : null;
}
