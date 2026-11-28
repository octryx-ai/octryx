// Agents & workflows → Overview → Effective setup: what an octryx-claude session gets, each part with source,
// version and enforcement.
import { Fragment } from "react";

import { useAdminNavigation } from "../../../adminNavigation";
import { resolveAdminAreaForTab } from "../../../config/adminPanelAreas";
import type { AdminTab } from "../../../types/adminPanelTypes.governance";
import { ClassBadge, EnforcedBadge } from "../awBadges";
import "../agentsWorkflows.css";
import { budgetShares, type EffectiveSetup, type SetupPart } from "./effectiveSetupModel";
import { SetupPartBody } from "./SetupPartBody";
import { useEffectiveSetup } from "./useEffectiveSetup";

const BUDGET_CLASSES = ["b1", "b2", "b3"];

type Page = ReturnType<typeof useEffectiveSetup>;

export function EffectiveSetupPage() {
  const { openAdminTab } = useAdminNavigation();
  const page = useEffectiveSetup();
  const { setup, problem, loading } = page;
  const openSource = (tab: string | null) => {
    if (tab) openAdminTab(tab as AdminTab);
  };

  return (
    <div className="aw-page" data-testid="effective-setup">
      <p className="admin-panel__hint">
        What an octryx-claude session gets for the chosen Workspace, user, agent and workflow. Every part names its
        source, version and what enforces it.
      </p>
      <section className="admin-panel__card" aria-label="Setup inputs">
        <SetupPickers page={page} />
      </section>
      {problem ? <p className="admin-panel__error" role="alert">{problem}</p> : null}
      {!setup && loading ? <p className="admin-panel__hint" role="status">Preparing the setup…</p> : null}
      {setup ? (
        <div className="aw-split">
          <div className="aw-layers" data-testid="effective-setup-parts">
            {setup.parts.map((part, index) => (
              <SetupPartLayer key={part.id} part={part} index={index} setup={setup} openSource={openSource} />
            ))}
          </div>
          <SetupSide setup={setup} />
        </div>
      ) : null}
    </div>
  );
}

function SetupPickers({ page: { query, options, change } }: { page: Page }) {
  return (
    <div className="aw-pickers">
      <label className="admin-panel__field">
        <span>Workspace</span>
        <select value={query.projectId} onChange={(event) => change({ projectId: event.target.value, agentId: "", workflowKey: "" })}>
          <option value="">No Workspace</option>
          {options.projects.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
      </label>
      <label className="admin-panel__field">
        <span>User</span>
        <select value={query.userId} onChange={(event) => change({ userId: event.target.value })}>
          <option value="">Current user</option>
          {options.users.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
      </label>
      <label className="admin-panel__field">
        <span>Agent</span>
        <select value={query.agentId} onChange={(event) => change({ agentId: event.target.value })}>
          <option value="">No agent</option>
          {options.agents.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
      </label>
      <label className="admin-panel__field">
        <span>Workflow</span>
        <select value={query.workflowKey} onChange={(event) => change({ workflowKey: event.target.value })}>
          <option value="">Automatic</option>
          <option value="none">No workflow</option>
          {options.workflows.map((item) => (
            <option key={item.key} value={item.key}>{`${item.key} · ${item.capability.replace("_", "-")}`}</option>
          ))}
        </select>
      </label>
    </div>
  );
}

type LayerProps = { part: SetupPart; index: number; setup: EffectiveSetup; openSource: (tab: string | null) => void };

function SetupPartLayer({ part, index, setup, openSource }: LayerProps) {
  const workflowPartIndex = setup.parts.findIndex((entry) => entry.id === "workflow");
  return (
    <details className="aw-layer" open={index === workflowPartIndex}>
      <summary className="aw-layer__head">
        <span className="aw-layer__n">{index + 1}</span>
        <div>
          <div className="aw-layer__title">{part.title}</div>
          <div className="aw-layer__src">
            {part.sourceTab ? (
              <a className="aw-link"
                href={`?area=${resolveAdminAreaForTab(part.sourceTab as AdminTab)}&tab=${part.sourceTab}`}
                onClick={(event) => { event.preventDefault(); openSource(part.sourceTab); }}>
                {part.sourceLabel}
              </a>
            ) : part.sourceLabel}
            {part.version ? ` · ${part.version}` : ""}
          </div>
        </div>
        <div className="aw-row">
          {part.tokens ? <span className="aw-sub aw-sub--flush">{part.tokens} tok</span> : null}
          <EnforcedBadge value={part.enforced} />
        </div>
      </summary>
      <div className="aw-layer__body"><SetupPartBody part={part} /></div>
    </details>
  );
}

function SetupSide({ setup }: { setup: EffectiveSetup }) {
  return (
    <aside className="aw-side">
      <section className="admin-panel__card">
        <div className="admin-panel__section-header"><span>Summary</span></div>
        <dl className="aw-kv">
          <dt>Runtime</dt><dd>octryx-claude (Claude Code)</dd>
          <dt>Capability</dt><dd><ClassBadge value={setup.capabilityClass} /></dd>
          <dt>Workflow</dt><dd>{setup.workflowKey || "none"}</dd>
          <dt>Turn state</dt><dd>{setup.profileStatus || "–"}</dd>
          <dt>Sources</dt><dd>{`${setup.parts.length} parts · all versioned`}</dd>
        </dl>
      </section>
      <section className="admin-panel__card">
        <div className="admin-panel__section-header">
          <span>Token budget</span>
          <span className="aw-sub aw-sub--flush">
            {setup.budget.limit ? `${setup.budget.total} / ${setup.budget.limit} tokens` : `${setup.budget.total} tokens`}
          </span>
        </div>
        <div className="aw-budget">
          <div className="aw-bar">
            {budgetShares(setup.budget).map((group, index) => (
              <span key={group.key} className={BUDGET_CLASSES[index]} style={{ width: `${group.percent}%` }} />
            ))}
          </div>
          <div className="aw-legend">
            {setup.budget.groups.map((group, index) => (
              <Fragment key={group.key}>
                <span className={`aw-sw ${BUDGET_CLASSES[index]}`} />
                <span>{group.label}</span>
                <span>{group.tokens}</span>
              </Fragment>
            ))}
          </div>
        </div>
      </section>
      <div className="aw-note">
        Policies are not prompt text. They act on the tool surface and at dispatch, so this view lists them as
        <b> tools offered / forbidden</b> with the rule that decides.
      </div>
    </aside>
  );
}
