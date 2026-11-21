import { useEffect, useState } from "react";

import { loadFile } from "./skillCatalogApi";
import { refusalText } from "./skillCatalogModel";

export type FileState = { content: string | null; problem: string | null; loading: boolean };

/** One file of a version (`GET …/versions/{v}/files?path=`); `path` null loads nothing. */
export function useSkillFile(skillId: string, version: number | null, path: string | null): FileState {
  const [state, setState] = useState<FileState>({ content: null, problem: null, loading: false });
  useEffect(() => {
    if (version === null || !path) {
      setState({ content: null, problem: null, loading: false });
      return undefined;
    }
    let alive = true;
    setState({ content: null, problem: null, loading: true });
    loadFile(skillId, version, path)
      .then((raw) => {
        const content = (raw as { content?: unknown }).content;
        if (alive) setState({ content: typeof content === "string" ? content : "", problem: null, loading: false });
      })
      .catch((error: unknown) => { if (alive) setState({ content: null, problem: refusalText(error), loading: false }); });
    return () => { alive = false; };
  }, [skillId, version, path]);
  return state;
}
