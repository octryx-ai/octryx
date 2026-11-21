import { useEffect, useState } from "react";

import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import { readErrorMessage } from "./obFormat";
import type { RunDetail } from "./runsModel";

export type RunContent = { input_messages: unknown; output: unknown };

// The run's detail (loaded once per run), its content (an audited read on request) and whether the setup is shown.
export function useRunDetail(readJson: ReadJsonFn, runKey: string) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [content, setContent] = useState<RunContent | null>(null);
  const [showSetup, setShowSetup] = useState(false);

  useEffect(() => {
    let active = true;
    readJson<RunDetail>(`/api/v1/observability/runs/detail?run_key=${encodeURIComponent(runKey)}`)
      .then((payload) => active && setDetail(payload))
      .catch((loadError) => active && setError(readErrorMessage(loadError, "The run could not be loaded.")));
    return () => {
      active = false;
    };
  }, [readJson, runKey]);

  const showContent = async () => {
    try {
      setContent(await readJson<RunContent>(
        `/api/v1/observability/runs/content?run_key=${encodeURIComponent(runKey)}`,
        { method: "POST" },
      ));
    } catch (loadError) {
      setError(readErrorMessage(loadError, "The content could not be loaded."));
    }
  };

  return { detail, error, content, showSetup, setShowSetup, showContent };
}
