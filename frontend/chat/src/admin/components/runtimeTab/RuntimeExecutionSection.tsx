import { RuntimeArtifactStoreFields } from "./RuntimeArtifactStoreFields";
import { RuntimeExecutionIsolationFields } from "./RuntimeExecutionIsolationFields";
import { RuntimeWorkspaceCleanupFields } from "./RuntimeWorkspaceCleanupFields";
import { RuntimeWorkspaceStorageFields } from "./RuntimeWorkspaceStorageFields";
import { executionModeChanged, executionModeSummary } from "./executionModeSummary";
import type { RuntimeTabCtx } from "./types";
import "./runtimeSections.css";

type RuntimeExecutionSectionProps = {
  ctx: RuntimeTabCtx;
};

// Execution & storage page: the effective mode first, then one labelled group
// per concern. Isolation, storage and cleanup are saved together, and only
// their keys are sent; the artifact store keeps its own narrow save.
export function RuntimeExecutionSection({ ctx }: RuntimeExecutionSectionProps) {
  const {
    handleSaveRuntimeSettings,
    runtimeExecutionAllowHostFallback,
    runtimeExecutionProviderDraft,
    runtimeSettings,
  } = ctx;
  const effective = executionModeSummary(runtimeSettings);
  const pending = executionModeChanged(runtimeSettings, {
    execution_runtime_provider: runtimeExecutionProviderDraft,
    execution_runtime_allow_host_fallback: runtimeExecutionAllowHostFallback,
  });
  const pendingSummary = executionModeSummary({
    ...runtimeSettings,
    execution_runtime_provider: runtimeExecutionProviderDraft,
    execution_runtime_allow_host_fallback: runtimeExecutionAllowHostFallback,
  });

  return (
    <div className="admin-panel__subsection runtime-panel__card">
      <div className="runtime-execution__mode" role="status">
        <div className="runtime-execution__mode-line">
          Shell and scripts run on: <strong>{effective.target}</strong>
        </div>
        <div className="admin-panel__hint">{effective.detail}</div>
        {pending ? (
          <div className="admin-panel__hint">
            Unsaved change: after saving, commands run on{" "}
            <strong>{pendingSummary.target}</strong>.
          </div>
        ) : null}
      </div>

      <RuntimeExecutionIsolationFields ctx={ctx} />
      <RuntimeWorkspaceStorageFields ctx={ctx} />
      <RuntimeWorkspaceCleanupFields ctx={ctx} />

      <div className="admin-panel__form-actions">
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={() => void handleSaveRuntimeSettings("execution")}
        >
          Save runtime settings
        </button>
      </div>

      <RuntimeArtifactStoreFields ctx={ctx} />
    </div>
  );
}
