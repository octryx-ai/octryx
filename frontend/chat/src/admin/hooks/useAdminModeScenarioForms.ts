import { type Dispatch, type FormEvent, type SetStateAction } from "react";
import {
  DEFAULT_SCENARIO_EXECUTION_CONFIG,
  DEFAULT_SCENARIO_MATCH_CONFIG,
  DEFAULT_SCENARIO_PLANNER_CONFIG,
  withoutUnsupportedScenarioFields,
} from "../config/scenarioConfigFields";
import type { AdminScenarioProfile } from "../types/adminPanelTypes.governance";

type ReadJsonFn = <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;

type UseAdminModeScenarioFormsArgs = {
  readJson: ReadJsonFn;
  setShowScenarioForm: Dispatch<SetStateAction<boolean>>;
  editingScenarioId: string | null;
  setEditingScenarioId: Dispatch<SetStateAction<string | null>>;
  scenarioName: string;
  setScenarioName: Dispatch<SetStateAction<string>>;
  scenarioDescription: string;
  setScenarioDescription: Dispatch<SetStateAction<string>>;
  scenarioProjectId: string;
  setScenarioProjectId: Dispatch<SetStateAction<string>>;
  scenarioPriority: number;
  setScenarioPriority: Dispatch<SetStateAction<number>>;
  scenarioMatchConfig: string;
  setScenarioMatchConfig: Dispatch<SetStateAction<string>>;
  scenarioPlannerConfig: string;
  setScenarioPlannerConfig: Dispatch<SetStateAction<string>>;
  scenarioExecutionConfig: string;
  setScenarioExecutionConfig: Dispatch<SetStateAction<string>>;
  scenarioActive: boolean;
  setScenarioActive: Dispatch<SetStateAction<boolean>>;
  setScenarioFormLoading: Dispatch<SetStateAction<boolean>>;
  setScenarioFormError: Dispatch<SetStateAction<string | null>>;
  setScenarioProfiles: Dispatch<SetStateAction<AdminScenarioProfile[]>>;
};

export function useAdminModeScenarioForms(args: UseAdminModeScenarioFormsArgs) {
  const {
    readJson, setShowScenarioForm, editingScenarioId, setScenarioFormLoading, setScenarioFormError, setScenarioProfiles,
  } = args;
  const resetScenarioForm = () => resetScenarioFields(args);

  const openScenarioForm = (profile?: AdminScenarioProfile) => {
    if (!profile) {
      resetScenarioForm();
      setShowScenarioForm(true);
      return;
    }
    fillScenarioForm(args, profile);
  };

  const closeScenarioForm = () => {
    setShowScenarioForm(false);
    resetScenarioForm();
  };

  const handleSaveScenario = async (event: FormEvent) => {
    event.preventDefault();
    setScenarioFormError(null);
    setScenarioFormLoading(true);
    try {
      const url = editingScenarioId ? `/admin/chat/api/panel/scenarios/${editingScenarioId}` : "/admin/chat/api/panel/scenarios";
      const method = editingScenarioId ? "PUT" : "POST";
      const saved = await readJson<AdminScenarioProfile>(url, { method, body: JSON.stringify(scenarioPayload(args)) });
      setScenarioProfiles((prev) => (editingScenarioId ? prev.map((item) => (item.id === saved.id ? saved : item)) : [saved, ...prev]));
      closeScenarioForm();
    } catch (error) {
      setScenarioFormError(error instanceof Error ? error.message : "Failed to save scenario profile");
    } finally {
      setScenarioFormLoading(false);
    }
  };

  const handleDeleteScenario = async (scenarioId: string, name: string) => {
    if (!window.confirm(`Delete scenario profile "${name}"?`)) return;
    try {
      await readJson(`/admin/chat/api/panel/scenarios/${scenarioId}`, { method: "DELETE" });
      setScenarioProfiles((prev) => prev.filter((item) => item.id !== scenarioId));
      if (editingScenarioId === scenarioId) {
        closeScenarioForm();
      }
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Failed to delete scenario profile");
    }
  };

  return {
    closeScenarioForm,
    handleDeleteScenario,
    handleSaveScenario,
    openScenarioForm,
  };
}

function resetScenarioFields(args: UseAdminModeScenarioFormsArgs) {
  args.setEditingScenarioId(null);
  args.setScenarioName("");
  args.setScenarioDescription("");
  args.setScenarioProjectId("");
  args.setScenarioPriority(100);
  args.setScenarioMatchConfig(DEFAULT_SCENARIO_MATCH_CONFIG);
  args.setScenarioPlannerConfig(DEFAULT_SCENARIO_PLANNER_CONFIG);
  args.setScenarioExecutionConfig(DEFAULT_SCENARIO_EXECUTION_CONFIG);
  args.setScenarioActive(true);
  args.setScenarioFormError(null);
}

// The form filled from a saved profile, for editing.
function fillScenarioForm(args: UseAdminModeScenarioFormsArgs, profile: AdminScenarioProfile) {
  args.setEditingScenarioId(profile.id);
  args.setScenarioName(profile.name);
  args.setScenarioDescription(profile.description || "");
  args.setScenarioProjectId(profile.project_id || "");
  args.setScenarioPriority(profile.priority ?? 100);
  args.setScenarioMatchConfig(JSON.stringify(profile.match_config || {}, null, 2));
  args.setScenarioPlannerConfig(JSON.stringify(profile.planner_config || {}, null, 2));
  args.setScenarioExecutionConfig(JSON.stringify(profile.execution_config || {}, null, 2));
  args.setScenarioActive(profile.is_active);
  args.setScenarioFormError(null);
  args.setShowScenarioForm(true);
}

function parseConfig(text: string, label: string): Record<string, unknown> {
  try {
    return JSON.parse(text || "{}") as Record<string, unknown>;
  } catch {
    throw new Error(`${label} config must be valid JSON`);
  }
}

// The saved body; a config that is not valid JSON throws, in the order match, planner, execution.
function scenarioPayload(args: UseAdminModeScenarioFormsArgs) {
  const matchConfig = parseConfig(args.scenarioMatchConfig, "Match");
  const plannerConfig = parseConfig(args.scenarioPlannerConfig, "Planner");
  const executionConfig = parseConfig(args.scenarioExecutionConfig, "Execution");
  return {
    name: args.scenarioName,
    description: args.scenarioDescription,
    project_id: args.scenarioProjectId || null,
    priority: args.scenarioPriority,
    // Prompt matchers and tool fields are never written; the server refuses them.
    match_config: withoutUnsupportedScenarioFields("match_config", matchConfig),
    planner_config: withoutUnsupportedScenarioFields("planner_config", plannerConfig),
    execution_config: withoutUnsupportedScenarioFields("execution_config", executionConfig),
    is_active: args.scenarioActive,
  };
}
