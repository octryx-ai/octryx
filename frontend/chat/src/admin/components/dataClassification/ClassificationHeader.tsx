import { useAdminNavigation } from "../../adminNavigation";
import "../settingsKit/settingsKit.css";
import type { ClassificationLevel } from "./dataClassificationTypes";

const ENGINE_MODE_TEXT: Record<string, { badge: string; label: string; sub: string }> = {
  off: { badge: "work-badge--neutral", label: "Off", sub: "Rules are enforced by the platform checks; Cedar is not consulted." },
  shadow: { badge: "work-badge--running", label: "Shadow", sub: "Rules are enforced by the platform checks; Cedar compares." },
  enforce: { badge: "work-badge--active", label: "Enforce", sub: "Rules are enforced by the platform checks and by Cedar." },
};

type Props = {
  levels: ClassificationLevel[];
  defaultLevel: string | null;
  publishedDefault: string | null;
  unclassified: number | null;
  engineMode: string | null;
  editable: boolean;
  busy: boolean;
  onDefaultLevel: (level: string | null) => void;
  onApplyDefault: () => void;
};

// The header strip of Settings → Governance → Classification (the "Default data
// classification"): the level a new Workspace gets at creation (part of the governed draft), the Workspaces without a
// level with a one-off apply of the published level, and the policy engine mode.
export function ClassificationHeader({ levels, defaultLevel, publishedDefault, unclassified, engineMode, editable, busy,
  onDefaultLevel, onApplyDefault }: Props) {
  const { openAdminTab } = useAdminNavigation();
  const engine = engineMode ? ENGINE_MODE_TEXT[engineMode] : null;
  const publishedLabel = levels.find((level) => level.value === publishedDefault)?.label ?? null;
  return (
    <div className="sk-headstrip" data-testid="classification-header">
      <div className="sk-kpi">
        <span className="sk-kpi__l">Level for new Workspaces</span>
        <label className="admin-panel__field">
          <span className="sk-sr-only">Level for new Workspaces</span>
          <select value={defaultLevel ?? ""} disabled={!editable || busy} data-testid="classification-default-level"
            onChange={(event) => onDefaultLevel(event.target.value || null)}>
            <option value="">No level</option>
            {levels.map((level) => <option key={level.value} value={level.value}>{level.label}</option>)}
          </select>
        </label>
        <span className="sk-sub">Applied when a Workspace is created. Never used as a fallback at run time.</span>
      </div>
      <div className="sk-kpi">
        <span className="sk-kpi__l">Workspaces without a level</span>
        <span className="sk-kpi__v" data-testid="classification-unclassified">{unclassified ?? "–"}</span>
        <span className="sk-sub">
          Without a level, seats and remote models are refused.{" "}
          {editable && unclassified && publishedDefault ? (
            <button type="button" className="sk-link" disabled={busy} data-testid="classification-apply-default" onClick={onApplyDefault}>
              Apply {publishedLabel ?? "the default"}
            </button>
          ) : null}
        </span>
      </div>
      <div className="sk-kpi">
        <span className="sk-kpi__l">Enforcement</span>
        <span className="sk-kpi__v">
          {engine ? <span className={`work-badge ${engine.badge}`} data-testid="classification-engine-mode">{engine.label}</span> : "–"}
        </span>
        <span className="sk-sub">
          {engine ? engine.sub : "The policy engine mode could not be read."}{" "}
          <button type="button" className="sk-link" onClick={() => openAdminTab("cedarPolicies")}>Policies</button>
        </span>
      </div>
    </div>
  );
}
