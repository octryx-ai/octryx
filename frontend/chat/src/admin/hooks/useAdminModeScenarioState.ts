import { useState } from "react";
import {
  DEFAULT_SCENARIO_EXECUTION_CONFIG,
  DEFAULT_SCENARIO_MATCH_CONFIG,
  DEFAULT_SCENARIO_PLANNER_CONFIG,
} from "../config/scenarioConfigFields";

export function useAdminModeScenarioState() {
  const [showScenarioForm, setShowScenarioForm] = useState(false);
  const [editingScenarioId, setEditingScenarioId] = useState<string | null>(
    null,
  );
  const [scenarioName, setScenarioName] = useState("");
  const [scenarioDescription, setScenarioDescription] = useState("");
  const [scenarioProjectId, setScenarioProjectId] = useState("");
  const [scenarioPriority, setScenarioPriority] = useState(100);
  const [scenarioMatchConfig, setScenarioMatchConfig] = useState(
    DEFAULT_SCENARIO_MATCH_CONFIG,
  );
  const [scenarioPlannerConfig, setScenarioPlannerConfig] = useState(
    DEFAULT_SCENARIO_PLANNER_CONFIG,
  );
  const [scenarioExecutionConfig, setScenarioExecutionConfig] = useState(
    DEFAULT_SCENARIO_EXECUTION_CONFIG,
  );
  const [scenarioActive, setScenarioActive] = useState(true);
  const [scenarioFormLoading, setScenarioFormLoading] = useState(false);
  const [scenarioFormError, setScenarioFormError] = useState<string | null>(
    null,
  );

  return {
    editingScenarioId,
    setEditingScenarioId,
    scenarioActive,
    setScenarioActive,
    scenarioDescription,
    setScenarioDescription,
    scenarioExecutionConfig,
    setScenarioExecutionConfig,
    scenarioFormError,
    setScenarioFormError,
    scenarioFormLoading,
    setScenarioFormLoading,
    scenarioMatchConfig,
    setScenarioMatchConfig,
    scenarioName,
    setScenarioName,
    scenarioPlannerConfig,
    setScenarioPlannerConfig,
    scenarioPriority,
    setScenarioPriority,
    scenarioProjectId,
    setScenarioProjectId,
    showScenarioForm,
    setShowScenarioForm,
  };
}
