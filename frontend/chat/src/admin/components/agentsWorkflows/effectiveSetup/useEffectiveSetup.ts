// The effective setup page's state: the chosen inputs, the picker options and the prepared setup.
import { useCallback, useEffect, useState } from "react";

import { readJson } from "../../../utils/adminPanelHelpers";
import {
  EFFECTIVE_SETUP_PATH, readEffectiveSetup, readSetupOptions, setupQueryString,
  type EffectiveSetup, type SetupOptions, type SetupQuery,
} from "./effectiveSetupModel";

const EMPTY_OPTIONS: SetupOptions = { projects: [], users: [], agents: [], workflows: [] };

const errorText = (error: unknown) =>
  error instanceof Error && error.message ? error.message : "The effective setup could not be loaded.";

export function useEffectiveSetup() {
  const [query, setQuery] = useState<SetupQuery>({ projectId: "", userId: "", agentId: "", workflowKey: "" });
  const [options, setOptions] = useState<SetupOptions>(EMPTY_OPTIONS);
  const [setup, setSetup] = useState<EffectiveSetup | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const params = query.projectId ? `?project_id=${encodeURIComponent(query.projectId)}` : "";
    readJson<unknown>(`${EFFECTIVE_SETUP_PATH}/options${params}`)
      .then((raw) => setOptions(readSetupOptions(raw)))
      .catch(() => setOptions(EMPTY_OPTIONS));
  }, [query.projectId]);

  const load = useCallback(async () => {
    setLoading(true);
    setProblem(null);
    try {
      const params = setupQueryString(query);
      setSetup(readEffectiveSetup(await readJson<unknown>(params ? `${EFFECTIVE_SETUP_PATH}?${params}` : EFFECTIVE_SETUP_PATH)));
    } catch (error) {
      setProblem(errorText(error));
    } finally {
      setLoading(false);
    }
  }, [query]);

  useEffect(() => { void load(); }, [load]);

  const change = (patch: Partial<SetupQuery>) => setQuery((current) => ({ ...current, ...patch }));
  return { query, options, setup, problem, loading, change };
}
