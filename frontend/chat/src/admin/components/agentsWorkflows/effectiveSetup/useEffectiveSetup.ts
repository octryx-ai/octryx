// The effective setup page's state: the chosen inputs (or a past session to compare with), the picker options, the
// prepared setup and the compare drawer.
import { useCallback, useEffect, useState } from "react";

import { readJson } from "../../../utils/adminPanelHelpers";
import {
  EFFECTIVE_SETUP_PATH, readEffectiveSetup, readSessionFromSearch, readSetupOptions, setupQueryString,
  type EffectiveSetup, type SetupOptions, type SetupQuery,
} from "./effectiveSetupModel";

const EMPTY_OPTIONS: SetupOptions = { projects: [], users: [], agents: [], workflows: [] };

const errorText = (error: unknown) =>
  error instanceof Error && error.message ? error.message : "The effective setup could not be loaded.";

export function useEffectiveSetup() {
  const [sessionId, setSessionId] = useState(() =>
    typeof window === "undefined" ? "" : readSessionFromSearch(window.location.search),
  );
  const [query, setQuery] = useState<SetupQuery>({ projectId: "", userId: "", agentId: "", workflowKey: "", runtime: "chat" });
  const [options, setOptions] = useState<SetupOptions>(EMPTY_OPTIONS);
  const [setup, setSetup] = useState<EffectiveSetup | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);
  const [compareDraft, setCompareDraft] = useState("");

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
      const raw = sessionId
        ? await readJson<unknown>(`${EFFECTIVE_SETUP_PATH}/sessions/${encodeURIComponent(sessionId)}`)
        : await readJson<unknown>(`${EFFECTIVE_SETUP_PATH}?${setupQueryString(query)}`);
      setSetup(readEffectiveSetup(raw));
    } catch (error) {
      setProblem(errorText(error));
    } finally {
      setLoading(false);
    }
  }, [query, sessionId]);

  useEffect(() => { void load(); }, [load]);

  const change = (patch: Partial<SetupQuery>) => {
    setSessionId("");
    setQuery((current) => ({ ...current, ...patch }));
  };
  return {
    setSessionId, query, options, setup, problem, loading, compareOpen, setCompareOpen, compareDraft, setCompareDraft, change,
  };
}
