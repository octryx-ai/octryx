import { SURFACES, SURFACE_LABELS } from "../skillCatalog/skillCatalogTypes";
import { assignedByLabel, categoryLabels, readinessBadge, reasonLabel } from "../skillCatalog/skillCatalogModel";
import type { Assignment, EffectiveRow } from "../skillCatalog/skillDeliveryTypes";
import { effectiveCount, refusalLines } from "../skillCatalog/workspaceSkillsModel";

// "Effective skills" of a Workspace (WP 2.7): what the server delivers per surface, how each skill is
// assigned and its readiness against the Workspace tool policy and the platform policies, then what is withheld and
// why. The set is computed by the server; with unsaved edits only the assigned preview count is local.
export function WorkspaceEffectiveSkills({ view, dirty, preview }: {
  view: Assignment;
  dirty: boolean;
  preview: number;
}) {
  const labels = categoryLabels(view.categories);
  const kind = (row: EffectiveRow) => (row.kind === "mcp_server" ? <> <span className="skills__kind">MCP</span></> : null);

  return (
    <div className="admin-panel__card" data-testid="ws-effective">
      <div className="admin-panel__section-header">
        Effective skills <span className="work-badge work-badge--neutral" data-testid="ws-effective-count">{dirty ? preview : effectiveCount(view)}</span>
      </div>
      {dirty ? (
        <p className="policies__note" role="status" data-testid="ws-preview">Unsaved changes: {preview} skill{preview === 1 ? "" : "s"} assigned
          before the surface and readiness checks. Save to see the effective set.</p>
      ) : null}
      {SURFACES.map((surface) => {
        const rows = view.effective[surface] ?? [];
        const withheld = view.withheld[surface] ?? [];
        return (
          <div key={surface} data-testid={`ws-effective-${surface}`}>
            <h4 className="skill-tabs__surface">{SURFACE_LABELS[surface]} · {rows.length}</h4>
            {rows.length ? (
              <div className="skills__scroll">
                <table className="admin-panel__table">
                  <thead><tr><th>Entry</th><th>Via</th><th>Readiness</th></tr></thead>
                  <tbody>
                    {rows.map((row) => {
                      const badge = readinessBadge(row.readiness);
                      return (
                        <tr key={row.skill_id}>
                          <td><span className="skills__mono">{row.name}</span>{kind(row)} <span className="admin-panel__cell--muted">v{row.version}</span>
                            {row.category_path.length ? <div className="policies__sub">{row.category_path.join(" / ")}</div> : null}</td>
                          <td className="admin-panel__cell--muted">{assignedByLabel(row.assigned_by, labels)}</td>
                          <td><span className={badge.className}>{badge.label}</span>
                            {refusalLines(row.readiness).map((line) => <div key={line} className="policies__sub">{line}</div>)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : <div className="admin-panel__empty-state">No catalog skills on this surface.</div>}
            {withheld.length ? (
              <div className="skills__scroll">
                <table className="admin-panel__table">
                  <thead><tr><th>Withheld</th><th>Reason</th></tr></thead>
                  <tbody>
                    {withheld.map((row) => (
                      <tr key={row.skill_id}>
                        <td><span className="skills__mono">{row.name}</span>{kind(row)} <span className="admin-panel__cell--muted">v{row.version}</span></td>
                        <td className="admin-panel__cell--muted">{reasonLabel(row.reason ?? "")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
        );
      })}
      <p className="skills__hint">Readiness compares each skill&apos;s required tools with this Workspace&apos;s tool policy and the platform
        policies. A skill whose tools are blocked is still delivered, but the blocked steps are refused. Assignment never changes a policy.</p>
    </div>
  );
}
