import { useEffect, useState } from "react";

import { loadSkillUsage } from "./skillCatalogApi";
import { refusalText, usageSplit } from "./skillCatalogModel";
import { formatWhen } from "./skillDetailModel";

type SkillUsage = { days: number; uses: number; refusals: number; by_surface: Record<string, number>; last_used_at: string | null };

// Detail → Usage (mock `renderDetail` usage KPIs): uses per surface over the window (octryx-claude model-invoked and
// slash, platform chat loads), refusals and the last use. Only counts are recorded, never prompts.
export function SkillDetailUsage({ skillId, kind }: { skillId: string; kind: string }) {
  const [usage, setUsage] = useState<SkillUsage | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    loadSkillUsage(skillId)
      .then((raw) => { if (alive) setUsage(raw as SkillUsage); })
      .catch((error: unknown) => { if (alive) setProblem(refusalText(error)); });
    return () => { alive = false; };
  }, [skillId]);

  if (problem) return <p className="policies__warn" role="alert">{problem}</p>;
  if (!usage) return <p className="admin-panel__hint" role="status">Loading usage…</p>;
  const split = usageSplit(usage.by_surface ?? {});
  const mcp = kind === "mcp_server";
  return (
    <div data-testid="skill-usage">
      <div className="policies__kpis">
        <div className="policies__kpi">
          <div className="policies__kpi-label">octryx-claude · {usage.days} days</div>
          <div className="policies__kpi-value">{split.model + split.slash}</div>
          <div className="policies__kpi-meta">{split.model} model-invoked · {split.slash} slash</div>
        </div>
        <div className="policies__kpi">
          <div className="policies__kpi-label">Platform chat · {usage.days} days</div>
          <div className="policies__kpi-value">{mcp ? "—" : split.chat}</div>
          <div className="policies__kpi-meta">{mcp ? "not available (local process)" : "skill_get loads"}</div>
        </div>
        <div className="policies__kpi">
          <div className="policies__kpi-label">Refused</div>
          <div className="policies__kpi-value">{usage.refusals}</div>
          <div className="policies__kpi-meta">refused by policy</div>
        </div>
      </div>
      <p className="skills__hint skill-detail__gap">
        Last used: {usage.last_used_at ? formatWhen(usage.last_used_at) : "not used in this window"}. Only the skill name, version digest,
        Workspace and session are recorded, never the prompt.
      </p>
    </div>
  );
}
