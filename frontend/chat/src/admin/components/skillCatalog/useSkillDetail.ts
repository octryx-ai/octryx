import { useCallback, useEffect, useState } from "react";

import { checkUpstream, loadSkill } from "./skillCatalogApi";
import { refusalText } from "./skillCatalogModel";
import type { SkillDetail, UpstreamStatus } from "./skillCatalogTypes";
import { checkSentence } from "./skillDetailModel";

export type DetailTab = "overview" | "files" | "versions" | "workspaces" | "security" | "delivery" | "usage";

// The detail page's state: the skill (reloaded when `revision` changes), the sub-tab (reset per skill), the
// upstream check result and the last change message.
export function useSkillDetail(skillId: string, initialSub: DetailTab | undefined, revision: number, onChanged: () => void | Promise<void>) {
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [sub, setSub] = useState<DetailTab>(initialSub ?? "overview");
  const [problem, setProblem] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [check, setCheck] = useState<{ text: string; tone: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      setDetail((await loadSkill(skillId)) as SkillDetail);
      setProblem(null);
    } catch (error) {
      setProblem(refusalText(error));
    }
  }, [skillId]);

  useEffect(() => { void reload(); }, [reload, revision]);
  useEffect(() => { setSub(initialSub ?? "overview"); }, [skillId, initialSub]);

  const changed = useCallback(async (text: string) => {
    setMessage(text);
    await reload();
    await onChanged();
  }, [reload, onChanged]);

  return { detail, sub, setSub, problem, message, check, setCheck, busy, setBusy, reload, changed };
}

// "Check for updates": asks the source, says what it found, then reloads the skill and the catalog.
export async function runUpstreamCheck(state: ReturnType<typeof useSkillDetail>, skillId: string, onChanged: () => void | Promise<void>) {
  const { setBusy, setCheck, reload } = state;
  setBusy(true);
  setCheck(null);
  try {
    const status = (await checkUpstream(skillId)) as UpstreamStatus;
    setCheck(checkSentence(status));
    await reload();
    await onChanged();
  } catch (error) {
    setCheck({ text: refusalText(error), tone: "error" });
  } finally {
    setBusy(false);
  }
}
