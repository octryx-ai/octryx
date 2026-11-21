import { GroupLabel } from "./BuilderChips";
import type { CatalogTemplate } from "./policyCatalogModel";

// Stroke icons (1.7, round caps) like the admin sidebar; keyed by the catalog's template icon name.
const ICONS: Record<string, string> = {
  shield: "M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z",
  model: "M4 6h16v12H4zM8 10h8M8 14h5",
  trash: "M5 7h14M9 7V4h6v3M7 7l1 13h8l1-13",
  lock: "M7 11V8a5 5 0 0 1 10 0v3M5 11h14v9H5z",
  restart: "M4 12a8 8 0 1 0 3-6.2M4 4v4h4",
  pulse: "M3 12h4l3-7 4 14 3-7h4",
  log: "M5 4h14v16H5zM9 8h6M9 12h6M9 16h3",
};

export function TemplateCard({ template, actionLabels, onUse }: { template: CatalogTemplate; actionLabels: string[]; onUse: () => void }) {
  return (
    <div className="policies__template" data-testid="policy-template">
      <div className="policies__flex-between">
        <div className="policies__template-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d={ICONS[template.icon] ?? ICONS.shield} /></svg></div>
        <div className="policies__row">{template.tags.map((tag) => <span key={tag} className="work-badge work-badge--neutral">{tag}</span>)}</div>
      </div>
      <h4>{template.label}</h4>
      <p>{template.description}</p>
      <div className="policies__sub">{actionLabels.join(" · ")}</div>
      <div><button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid={`policy-template-use-${template.id}`} onClick={onUse}>Use template</button></div>
    </div>
  );
}

// The Templates tab: the built-in templates of the catalog, the general ones first, then each
// catalog section (e.g. "Sensitive data in requests and tool results"). "Use template" opens the builder
// pre-filled; the template's placeholders (a connection, a role, the approved model …) are the only required inputs.
export function PolicyTemplates({ templates, labelOf, onUse }: { templates: CatalogTemplate[]; labelOf: (action: string) => string; onUse: (template: CatalogTemplate) => void }) {
  const sections = Array.from(new Set(templates.map((template) => template.section))).sort((a, b) => Number(Boolean(a)) - Number(Boolean(b)));
  return (
    <div data-testid="policy-templates">
      <p className="admin-panel__hint policies__templates-hint">Start from a proven pattern. A template opens the builder pre-filled; only the highlighted inputs (a connection, a role, the approved model) are required.</p>
      {sections.map((section) => (
        <div key={section || "general"} className="policies__pane" data-testid="policy-template-section">
          {section ? <GroupLabel>{section}</GroupLabel> : null}
          <div className="policies__templates">
            {templates.filter((template) => template.section === section).map((template) => (
              <TemplateCard key={template.id} template={template} onUse={() => onUse(template)}
                actionLabels={(Array.isArray(template.model.actions) ? template.model.actions as string[] : []).map(labelOf)} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
