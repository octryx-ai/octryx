// Admin › Scenarios: the match, planner and execution config sections of the scenario modal.
import { ROUTE_REASONS, TOOL_DOMAINS } from "../config/scenarioConstants";
import { MultiSelect, SectionBlock, ToggleRow } from "./ScenarioFormControls";
import type { parseScenarioExecutionConfig, parseScenarioMatchConfig, parseScenarioPlannerConfig } from "./scenarioFormConfig";

type MatchState = ReturnType<typeof parseScenarioMatchConfig>;
type PlannerState = ReturnType<typeof parseScenarioPlannerConfig>;
type ExecutionState = ReturnType<typeof parseScenarioExecutionConfig>;

export function ScenarioMatchSection({ match, syncMatch }: { match: MatchState; syncMatch: (next: MatchState) => void }) {
  return (
    <SectionBlock title="1 — When does this match? (Match Config)">
      <MultiSelect
        label="Route reasons"
        options={ROUTE_REASONS}
        selected={match.route_reasons}
        onChange={(v) => syncMatch({ ...match, route_reasons: v })}
        hint="The route reason assigned by the context planner. Match if any selected reason applies."
      />
      <MultiSelect
        label="Required domains"
        options={TOOL_DOMAINS}
        selected={match.required_domains}
        onChange={(v) => syncMatch({ ...match, required_domains: v })}
        hint="Match only if the current context already has these domains active."
      />
      <p className="admin-form-help">
        Prompt text never selects a scenario: match on route reasons
        and domains.
      </p>
    </SectionBlock>
  );
}

export function ScenarioPlannerSection({ planner, syncPlanner }: {
  planner: PlannerState;
  syncPlanner: (next: PlannerState) => void;
}) {
  return (
    <SectionBlock title="2 — How to plan context (Planner Config)">
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: "0.15rem",
        }}
      >
        <ToggleRow
          label="Include skills"
          hint="Include skill definitions and metadata"
          value={planner.include_skills}
          onChange={(v) =>
            syncPlanner({ ...planner, include_skills: v })
          }
        />
        <ToggleRow
          label="Include system context"
          hint="Add system-level instructions and config"
          value={planner.include_system_context}
          onChange={(v) =>
            syncPlanner({ ...planner, include_system_context: v })
          }
        />
        <ToggleRow
          label="Include recent history"
          hint="Load the last N messages in this session"
          value={planner.include_recent_history}
          onChange={(v) =>
            syncPlanner({ ...planner, include_recent_history: v })
          }
        />
        <ToggleRow
          label="Include summary context"
          hint="Add conversation summarization metadata"
          value={planner.include_summary_context}
          onChange={(v) =>
            syncPlanner({ ...planner, include_summary_context: v })
          }
        />
      </div>

      <p className="admin-form-help">
        Scenarios do not set tools: the tool surface comes from the
        selected workflow definition, the agent definition or the
        Workspace tool policy.
      </p>
      <div className="admin-form-grid">
        <div className="admin-form-field">
          <label htmlFor="scenario-token-budget">Token budget</label>
          <input
            id="scenario-token-budget"
            type="number"
            className="connector-field__input"
            value={planner.token_budget}
            onChange={(e) =>
              syncPlanner({ ...planner, token_budget: e.target.value })
            }
            placeholder="e.g. 20000 (empty = use default)"
          />
          <span className="admin-form-help">
            Overrides the default token budget for this scenario.
          </span>
        </div>
        <div className="admin-form-field">
          <label htmlFor="scenario-recent-history">
            Recent history limit
          </label>
          <input
            id="scenario-recent-history"
            type="number"
            className="connector-field__input"
            value={planner.recent_history_limit}
            onChange={(e) =>
              syncPlanner({
                ...planner,
                recent_history_limit: e.target.value,
              })
            }
            placeholder="e.g. 8"
          />
        </div>
      </div>
    </SectionBlock>
  );
}

export function ScenarioExecutionSection({ execution, syncExecution }: {
  execution: ExecutionState;
  syncExecution: (next: ExecutionState) => void;
}) {
  return (
    <SectionBlock title="3 — Execution guarantees (Execution Config)">
      <MultiSelect
        label="Required domains"
        options={TOOL_DOMAINS}
        selected={execution.required_domains}
        onChange={(v) =>
          syncExecution({ ...execution, required_domains: v })
        }
        hint="The agent must satisfy these domains before returning a result."
      />
      <ToggleRow
        label="Enforce domain coverage"
        hint="Block the response if not all required domains are satisfied"
        value={execution.enforce_domain_coverage}
        onChange={(v) =>
          syncExecution({ ...execution, enforce_domain_coverage: v })
        }
      />
    </SectionBlock>
  );
}
