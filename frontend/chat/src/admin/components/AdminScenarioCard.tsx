// Scenario profile card: match route reasons, planner context settings and execution domains of one scenario.
import { ROUTE_REASONS, TOOL_DOMAINS } from "../config/scenarioConstants";

type MatchConfig = {
  route_reasons?: unknown[];
  route_reason?: unknown;
  required_domains?: unknown[];
};

type PlannerConfig = {
  include_skills?: boolean;
  include_system_context?: boolean;
  include_recent_history?: boolean;
  include_summary_context?: boolean;
  token_budget?: number;
  system_prompt_variant?: string;
  recent_history_limit?: number;
};

type ExecutionConfig = {
  required_domains?: unknown[];
  enforce_domain_coverage?: boolean;
};

export type ScenarioProfileRow = {
  id: string;
  project_id: string | null;
  name: string;
  description: string;
  priority: number;
  match_config: MatchConfig;
  planner_config: PlannerConfig;
  execution_config: ExecutionConfig;
  is_active: boolean;
};

function parseStrList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  return [];
}

export function ScenarioCard({
  profile,
  projectNameById,
  onEdit,
  onDelete,
}: {
  profile: ScenarioProfileRow;
  projectNameById: Map<string, string>;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const match = profile.match_config || {};
  const planner = profile.planner_config || {};
  const execution = profile.execution_config || {};

  const routeReasons = parseStrList(match.route_reasons || match.route_reason);
  const requiredDomains = parseStrList(
    execution.required_domains || match.required_domains || [],
  );
  const tokenBudget = planner.token_budget ?? null;

  const activeCount = [
    planner.include_skills,
    planner.include_system_context,
    planner.include_recent_history,
    planner.include_summary_context,
  ].filter(Boolean).length;

  return (
    <div
      className={`task-item ${!profile.is_active ? "task-item--inactive" : ""}`}
    >
      <ScenarioHeader profile={profile} projectNameById={projectNameById} onEdit={onEdit} onDelete={onDelete} />

      {/* Match section */}
      <MatchSection routeReasons={routeReasons} />

      {/* Planner section */}
      {activeCount > 0 || tokenBudget !== null ? <PlannerSection activeCount={activeCount} tokenBudget={tokenBudget} /> : null}

      {/* Execution section */}
      {requiredDomains.length > 0 || execution.enforce_domain_coverage ? (
        <ExecutionSection requiredDomains={requiredDomains} enforce={execution.enforce_domain_coverage} />
      ) : null}
    </div>
  );
}

function ScenarioHeader({
  profile,
  projectNameById,
  onEdit,
  onDelete,
}: {
  profile: ScenarioProfileRow;
  projectNameById: Map<string, string>;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="task-item__row">
      <div
        className="task-item__status-dot"
        style={{
          background: profile.is_active
            ? "#4ade80"
            : "rgba(255,255,255,0.14)",
        }}
      />
      <div className="task-item__main">
        <div className="task-item__name">{profile.name}</div>
        <div className="task-item__desc">
          {profile.description || "No description."}
        </div>
      </div>
      <div className="task-item__meta">
        <span className="task-item__badge">Priority {profile.priority}</span>
        <span className="task-item__badge task-item__badge--secondary">
          {profile.project_id
            ? projectNameById.get(profile.project_id) || "Project"
            : "Global"}
        </span>
      </div>
      <div className="task-item__actions">
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={onEdit}
        >
          Edit
        </button>
        <button
          type="button"
          className="admin-panel__danger-btn"
          onClick={onDelete}
        >
          Delete
        </button>
      </div>
    </div>
  );
}

function MatchSection({ routeReasons }: { routeReasons: string[] }) {
  return (
    <div className="task-item__runs">
      <div className="admin-inline-actions">
        <span className="task-item__badge" style={{ fontWeight: 600 }}>
          MATCH
        </span>
        {routeReasons.length > 0 ? (
          routeReasons.map((reason) => {
            const meta = ROUTE_REASONS.find((r) => r.value === reason);
            return (
              <span
                key={reason}
                className="task-item__badge task-item__badge--primary"
                title={meta?.hint}
              >
                {meta?.label ?? reason}
              </span>
            );
          })
        ) : (
          <span className="task-item__badge task-item__badge--secondary">
            any route
          </span>
        )}
      </div>
    </div>
  );
}

function PlannerSection({ activeCount, tokenBudget }: { activeCount: number; tokenBudget: number | null }) {
  return (
    <div className="task-item__runs">
      <div className="admin-inline-actions">
        <span className="task-item__badge" style={{ fontWeight: 600 }}>
          PLANNER
        </span>
        {activeCount > 0 && (
          <span className="task-item__badge task-item__badge--secondary">
            +{activeCount} context
          </span>
        )}
        {tokenBudget !== null && (
          <span className="task-item__badge task-item__badge--secondary">
            budget: {tokenBudget}
          </span>
        )}
      </div>
    </div>
  );
}

function ExecutionSection({ requiredDomains, enforce }: { requiredDomains: string[]; enforce: boolean | undefined }) {
  return (
    <div className="task-item__runs">
      <div className="admin-inline-actions">
        <span className="task-item__badge" style={{ fontWeight: 600 }}>
          EXECUTION
        </span>
        {requiredDomains.map((d) => {
          const meta = TOOL_DOMAINS.find((t) => t.value === d);
          return (
            <span
              key={d}
              className="task-item__badge task-item__badge--primary"
              title={meta?.hint}
            >
              {meta?.label ?? d}
            </span>
          );
        })}
        {enforce && (
          <span className="task-item__badge task-item__badge--danger">
            enforce coverage
          </span>
        )}
      </div>
    </div>
  );
}
