import { useCallback, useEffect, useState } from "react";

import { loadCodingPipelines, saveCodingPipeline } from "../../work/workCodingApi";
import type { WorkCodingPipelineConfig } from "../../work/workCodingPipelineTypes";
import { CodingPipelineDrawer } from "../CodingPipelineDrawer";
import { DEFAULT_REVIEW_STATUS, knownValueOptions } from "../codingGovernanceForm";
import { DEFAULT_STAGES, EMPTY_PIPELINE_FORM, pipelineFormFromConfig, type PipelineForm } from "../codingPipelineForm";
import { CHECK_TYPES, checkDetail, EFFECT_TONES, type PipelineCheck } from "./codingRulesApi";
import "./codingRules.css";
import { LoadingState } from "../../../layout/LoadingState";
import { FormSection } from "../../../layout/FormSection";
import { SidePanel } from "../../../layout/SidePanel";


type NewCheck = { type: string; effect: PipelineCheck["effect"]; value: string };
const VALUE_FIELD: Record<string, { key: string; label: string; numeric: boolean } | undefined> = {
  pr_size_threshold: { key: "max_changed_lines", label: "Changed lines", numeric: true },
  file_line_threshold: { key: "max_file_lines", label: "Lines per file", numeric: true },
  branch_commit_naming: { key: "branch_pattern", label: "Branch pattern", numeric: false },
};

function checksOf(config: WorkCodingPipelineConfig): PipelineCheck[] {
  const checks = (config as { checks?: PipelineCheck[] }).checks ?? (config.controls?.checks as PipelineCheck[] | undefined);
  return Array.isArray(checks) ? checks : [];
}

// Coding → Delivery → Delivery pipeline: the stages every change runs through and the checks
// on every change. Denials of paths and commands are policies.
export function CodingDeliveryPipeline({ workspaceId }: { workspaceId: string }) {
  const [configs, setConfigs] = useState<WorkCodingPipelineConfig[] | null>(null);
  const [adding, setAdding] = useState<{ configId: string; draft: NewCheck } | null>(null);
  const [drawer, setDrawer] = useState<PipelineForm | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const all = await loadCodingPipelines();
      setConfigs(all.filter((config) => config.is_active && (!config.project_id || config.project_id === workspaceId)));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not load the delivery pipeline.");
    }
  }, [workspaceId]);
  useEffect(() => { void refresh(); }, [refresh]);

  async function addCheck(config: WorkCodingPipelineConfig, draft: NewCheck) {
    const field = VALUE_FIELD[draft.type];
    const value = field ? (field.numeric ? Number(draft.value) : draft.value.trim()) : null;
    if (field && (value === "" || (field.numeric && !Number.isFinite(value)))) {
      setError(`Enter the ${field.label.toLowerCase()}.`);
      return;
    }
    const check = { type: draft.type, effect: draft.effect, rule: field ? { [field.key]: value } : {} };
    try {
      await saveCodingPipeline({ ...config, checks: [...checksOf(config), check] } as Partial<WorkCodingPipelineConfig>);
      setAdding(null);
      setError(null);
      await refresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not add the check.");
    }
  }

  async function removeCheck(config: WorkCodingPipelineConfig, key: string) {
    try {
      await saveCodingPipeline({ ...config, checks: checksOf(config).filter((check) => check.key !== key) } as Partial<WorkCodingPipelineConfig>);
      await refresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not remove the check.");
    }
  }

  if (!configs) return error ? <div className="work-area__error">{error}</div> : <LoadingState label="the delivery pipeline" variant="page" />;
  return (
    <div className="coding-rules">
      {configs.length === 0 ? (
        <section className="admin-panel__card">
          <div className="admin-panel__section-header"><span>Delivery pipeline · built-in default</span>
            <span className="work-badge work-badge--neutral">default</span></div>
          <div className="coding-rules__stages">
            {DEFAULT_STAGES.map((stage, index) => <span key={stage.key}>{index ? <span className="coding-rules__arrow">→</span> : null}
              <span className={`coding-rules__stage ${stage.required ? "is-req" : ""}`}>{stage.label}</span></span>)}
          </div>
          <p className="admin-panel__hint">Sessions run these built-in steps without checks until the Workspace has its own pipeline.</p>
          <div><button type="button" className="admin-panel__action-btn" onClick={() => setDrawer({ ...EMPTY_PIPELINE_FORM, name: "Workspace default", project_id: workspaceId })}>Create the Workspace pipeline</button></div>
        </section>
      ) : configs.map((config) => (
        <section key={config.id} className="admin-panel__card" data-testid="delivery-pipeline">
          <div className="admin-panel__section-header">
            <span>Delivery pipeline · {config.project_id ? config.name : `${config.name} (every Workspace)`}</span>
            <span className={`work-badge ${config.review_status === "reviewed" ? "work-badge--active" : "work-badge--neutral"}`}>
              {config.review_status.replaceAll("_", " ")}</span>
          </div>
          <div className="coding-rules__stages">
            {config.stages.map((stage, index) => (
              <span key={String(stage.key)}>{index ? <span className="coding-rules__arrow">→</span> : null}
                <span className={`coding-rules__stage ${stage.required === false ? "" : "is-req"}`}>{String(stage.label ?? stage.key)}</span></span>
            ))}
            <button type="button" className="work-link" onClick={() => setDrawer(pipelineFormFromConfig(config))}>Edit stages</button>
          </div>
          <div className="admin-panel__section-header coding-rules__subhead"><span>Checks on every change</span>
            <button type="button" className="admin-panel__action-btn"
              onClick={() => setAdding({ configId: config.id, draft: { type: "pr_size_threshold", effect: "review", value: "" } })}>+ Add check</button></div>
          {checksOf(config).map((check) => (
            <div key={check.key} className="coding-rules__rule" data-testid="pipeline-check">
              <div><b>{check.label}</b><div className="work-sub">{checkDetail(check)}</div></div>
              <span className="coding-rules__actions">
                <span className={`work-badge work-badge--${EFFECT_TONES[check.effect] ?? "neutral"}`}>{check.effect}</span>
                <button type="button" className="work-link" onClick={() => void removeCheck(config, check.key)}>Remove</button>
              </span>
            </div>
          ))}
        </section>
      ))}
      {adding ? (
        // Create flow: a side panel over the dimmed page, labelled fields, Cancel + Add check at the bottom.
        <SidePanel title="Add check" subtitle={configs?.find((config) => config.id === adding.configId)?.name} onClose={() => setAdding(null)}
          testId="add-check"
          footer={(
            <>
              <button type="button" className="admin-panel__action-btn" onClick={() => setAdding(null)}>Cancel</button>
              <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" onClick={() => {
                const config = configs?.find((entry) => entry.id === adding.configId);
                if (config) void addCheck(config, adding.draft);
              }}>Add check</button>
            </>
          )}>
          {error ? <div className="work-area__error" role="alert">{error}</div> : null}
          <FormSection title="Check">
            <label className="admin-panel__field"><span>Check</span>
              <select className="admin-panel__input" value={adding.draft.type} onChange={(event) => setAdding({ ...adding, draft: { ...adding.draft, type: event.target.value, value: "" } })}>
                {Object.entries(CHECK_TYPES).map(([type, label]) => <option key={type} value={type}>{label}</option>)}
              </select></label>
            <label className="admin-panel__field"><span>When it fails</span>
              <select className="admin-panel__input" value={adding.draft.effect} onChange={(event) => setAdding({ ...adding, draft: { ...adding.draft, effect: event.target.value as PipelineCheck["effect"] } })}>
                <option value="warn">Warn</option><option value="review">Reviewer must confirm</option><option value="block">Block</option>
              </select></label>
            {VALUE_FIELD[adding.draft.type] ? (
              <label className="admin-panel__field"><span>{VALUE_FIELD[adding.draft.type]?.label}</span>
                <input className="admin-panel__input" value={adding.draft.value} onChange={(event) => setAdding({ ...adding, draft: { ...adding.draft, value: event.target.value } })} /></label>
            ) : null}
          </FormSection>
        </SidePanel>
      ) : null}
      {error && !adding ? <div className="work-area__error" role="alert">{error}</div> : null}
      {drawer ? (
        <CodingPipelineDrawer initial={drawer} reviewStatusOptions={knownValueOptions(DEFAULT_REVIEW_STATUS, configs.map((config) => config.review_status))} onClose={() => setDrawer(null)}
          onSaved={() => { setDrawer(null); void refresh(); }} />
      ) : null}
    </div>
  );
}
