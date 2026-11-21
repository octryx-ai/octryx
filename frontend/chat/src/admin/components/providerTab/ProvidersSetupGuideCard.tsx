import { useState } from "react";

import type { SetupGuideStatus, SetupGuideStep } from "../../types/adminPanelTypes.usersProviders";
import type { ProviderTabCtx } from "./types";
import "./providersSetupGuide.css";
import { setupGuideOpenSummary } from "./setupGuideSummary";

type ProvidersSetupGuideCardProps = {
  ctx: ProviderTabCtx;
};

function stepTone(step: SetupGuideStep) {
  if (step.status === "completed") return "completed";
  return step.blocking ? "required" : "recommended";
}

const STEP_STATE_LABEL = {
  completed: "Ready",
  required: "Required",
  recommended: "Recommended",
} as const;

// The read-only setup checklist. It sits below the provider list and starts
// collapsed once the backend reports the core setup as ready; while something
// still blocks, it opens by itself.
export function ProvidersSetupGuideCard({ ctx }: ProvidersSetupGuideCardProps) {
  const { handleSetupGuideAction, setupGuide } = ctx;
  // Setting up the local model starts a runtime: it asks once more instead of acting on the first click.
  const [confirming, setConfirming] = useState("");

  if (!setupGuide) {
    return null;
  }
  const steps: SetupGuideStep[] = setupGuide.steps;

  return (
    <details
      className="provider-card provider-card--guide providers-setup-guide"
      open={!setupGuide.ready}
    >
      <summary className="providers-setup-guide__summary">
        <span className="provider-card__name">Platform setup guide</span>
        <span
          className={`admin-panel__badge ${setupGuide.ready ? "admin-panel__badge--active" : "admin-panel__badge--warning"}`}
        >
          {setupGuide.ready ? "Ready" : "Needs action"}
        </span>
        <span className="provider-card__meta">
          {setupGuideOpenSummary(steps)}
        </span>
      </summary>
      <div className="provider-card__body provider-guide">
        <div className="provider-guide__header">
          <GuideStats stats={setupGuide.stats} />
        </div>
        <div className="provider-guide__steps">
          {steps.map((step) => (
            <GuideStep key={step.key} step={step} confirming={confirming} setConfirming={setConfirming}
              handleSetupGuideAction={handleSetupGuideAction} />
          ))}
        </div>
      </div>
    </details>
  );
}

// The guide's counts: active providers, API providers and runtimes.
function GuideStats({ stats }: { stats: SetupGuideStatus["stats"] }) {
  return (
    <div className="provider-guide__stats">
      <span className="provider-guide__stat">
        <strong>{stats.active_provider_count}</strong> active
        providers
      </span>
      <span className="provider-guide__stat">
        <strong>{stats.api_provider_count}</strong> API
      </span>
      <span className="provider-guide__stat">
        <strong>{stats.active_runtime_count}</strong> runtimes
      </span>
    </div>
  );
}

// One step on one line, with its action where the admin UI can resolve it.
function GuideStep({ step, confirming, setConfirming, handleSetupGuideAction }: {
  step: SetupGuideStep;
  confirming: string;
  setConfirming: (key: string) => void;
  handleSetupGuideAction: ProviderTabCtx["handleSetupGuideAction"];
}) {
  const tone = stepTone(step);
  return (
    <div
      className={`provider-guide-step provider-guide-step--${tone}`}
    >
      {/* One line per step: title, state and the current value; why it matters is the
          tooltip and the page help. */}
      <div className="provider-guide-step__body provider-guide-step__body--line" title={step.description}>
        <strong>{step.title}</strong>
        <span className="provider-guide-step__state">{STEP_STATE_LABEL[tone]}</span>
        {step.detail ? <span className="provider-card__meta provider-guide-step__detail">{step.detail}</span> : null}
      </div>
      {/* A step without an action is informational: nothing in the admin UI
          can resolve it directly, so no button is offered. */}
      {step.status !== "completed" && step.action ? (
        <button
          type="button"
          className="admin-panel__action-btn providers-setup-guide__action"
          onClick={() => {
            if (step.action === "configure_local_anchor" && confirming !== step.key) {
              setConfirming(step.key);
              return;
            }
            setConfirming("");
            void handleSetupGuideAction(step.action);
          }}
        >
          {confirming === step.key ? "Confirm: start it now" : step.action_label}
        </button>
      ) : null}
    </div>
  );
}
