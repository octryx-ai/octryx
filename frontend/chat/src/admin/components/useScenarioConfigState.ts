// Admin › Scenarios: the structured match, planner and execution state of the scenario modal, kept in
// sync with the JSON strings the save handler sends.
import React, { type Dispatch, type SetStateAction } from "react";
import { withoutUnsupportedScenarioFields } from "../config/scenarioConfigFields";
import { parseScenarioExecutionConfig, parseScenarioMatchConfig, parseScenarioPlannerConfig } from "./scenarioFormConfig";

type MatchState = ReturnType<typeof parseScenarioMatchConfig>;
type PlannerState = ReturnType<typeof parseScenarioPlannerConfig>;
type ExecutionState = ReturnType<typeof parseScenarioExecutionConfig>;

const existingConfig = (json: string) => JSON.parse(json || "{}") as Record<string, unknown>;
const pretty = (value: Record<string, unknown>) => JSON.stringify(value, null, 2);

export function syncedMatchConfig(current: string, next: MatchState): string {
  return pretty({
    ...withoutUnsupportedScenarioFields("match_config", existingConfig(current)),
    route_reasons: next.route_reasons,
    required_domains: next.required_domains,
  });
}

export function syncedPlannerConfig(current: string, next: PlannerState): string {
  const existing = existingConfig(current);
  const updates: Record<string, unknown> = {
    include_skills: next.include_skills,
    include_system_context: next.include_system_context,
    include_recent_history: next.include_recent_history,
    include_summary_context: next.include_summary_context,
  };
  if (next.token_budget) updates.token_budget = Number(next.token_budget);
  if (next.recent_history_limit)
    updates.recent_history_limit = Number(next.recent_history_limit);
  if (next.system_prompt_variant)
    updates.system_prompt_variant = next.system_prompt_variant;
  return pretty({
    ...withoutUnsupportedScenarioFields("planner_config", existing),
    ...updates,
  });
}

export function syncedExecutionConfig(current: string, next: ExecutionState): string {
  return pretty({
    ...withoutUnsupportedScenarioFields("execution_config", existingConfig(current)),
    required_domains: next.required_domains,
    enforce_domain_coverage: next.enforce_domain_coverage,
  });
}

export type ScenarioConfigStrings = {
  show: boolean;
  scenarioMatchConfig: string;
  setScenarioMatchConfig: Dispatch<SetStateAction<string>>;
  scenarioPlannerConfig: string;
  setScenarioPlannerConfig: Dispatch<SetStateAction<string>>;
  scenarioExecutionConfig: string;
  setScenarioExecutionConfig: Dispatch<SetStateAction<string>>;
};

export function useScenarioConfigState({
  show,
  scenarioMatchConfig,
  setScenarioMatchConfig,
  scenarioPlannerConfig,
  setScenarioPlannerConfig,
  scenarioExecutionConfig,
  setScenarioExecutionConfig,
}: ScenarioConfigStrings) {
  // Parse stored JSON into structured state for the form
  const parseMatchConfig = React.useCallback(() => parseScenarioMatchConfig(scenarioMatchConfig), [scenarioMatchConfig]);
  const parsePlannerConfig = React.useCallback(() => parseScenarioPlannerConfig(scenarioPlannerConfig), [scenarioPlannerConfig]);
  const parseExecutionConfig = React.useCallback(
    () => parseScenarioExecutionConfig(scenarioExecutionConfig),
    [scenarioExecutionConfig],
  );

  const [match, setMatch] = React.useState(parseMatchConfig);
  const [planner, setPlanner] = React.useState(parsePlannerConfig);
  const [execution, setExecution] = React.useState(parseExecutionConfig);

  // Keep local state in sync when modal opens with existing data
  React.useEffect(() => {
    setMatch(parseMatchConfig());
    setPlanner(parsePlannerConfig());
    setExecution(parseExecutionConfig());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [show]);

  // Sync structured changes back into JSON strings for the save handler
  const syncMatch = React.useCallback((next: MatchState) => {
    setMatch(next);
    setScenarioMatchConfig(syncedMatchConfig(scenarioMatchConfig, next));
  }, [scenarioMatchConfig, setScenarioMatchConfig]);
  const syncPlanner = React.useCallback((next: PlannerState) => {
    setPlanner(next);
    setScenarioPlannerConfig(syncedPlannerConfig(scenarioPlannerConfig, next));
  }, [scenarioPlannerConfig, setScenarioPlannerConfig]);
  const syncExecution = React.useCallback((next: ExecutionState) => {
    setExecution(next);
    setScenarioExecutionConfig(syncedExecutionConfig(scenarioExecutionConfig, next));
  }, [scenarioExecutionConfig, setScenarioExecutionConfig]);

  return { match, planner, execution, syncMatch, syncPlanner, syncExecution };
}
