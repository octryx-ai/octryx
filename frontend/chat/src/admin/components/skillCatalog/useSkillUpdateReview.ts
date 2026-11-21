// State and actions of the skill update review: the skill with its open update draft, the diff against the
// published version, and the create, resolve, submit and discard actions.
import { useCallback, useEffect, useState } from "react";

import { loadDiff, loadSkill, retireVersion, saveDraft, submitVersion, updateFromUpstream } from "./skillCatalogApi";
import { refusalText } from "./skillCatalogModel";
import type { FileDiff } from "./skillDiffModel";
import type { Resolution, SkillDetail } from "./skillCatalogTypes";
import { changedFiles, updateFailure, withResolution } from "./skillUpdateModel";

export function useSkillUpdateState(skillId: string) {
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [diff, setDiff] = useState<FileDiff[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [pathMissing, setPathMissing] = useState(false);

  const reload = useCallback(async () => {
    try {
      setDetail((await loadSkill(skillId)) as SkillDetail);
    } catch (error) {
      setProblem(refusalText(error));
    }
  }, [skillId]);

  useEffect(() => { void reload(); }, [reload]);

  const draft = detail?.open ?? null;
  const report = draft?.merge_report ?? null;

  const draftVersion = report ? draft?.version ?? null : null;
  const draftDigest = draft?.digest ?? "";
  useEffect(() => {
    let alive = true;
    if (draftVersion === null) return undefined;
    loadDiff(skillId, draftVersion, "published")
      .then((raw) => { if (alive) setDiff(changedFiles(((raw as { files?: FileDiff[] }).files) ?? [])); })
      .catch((error) => { if (alive) setProblem(refusalText(error)); });
    return () => { alive = false; };
  }, [skillId, draftVersion, draftDigest]);

  return { detail, diff, busy, setBusy, problem, setProblem, message, setMessage, pathMissing, setPathMissing, reload, draft, report };
}

type UpdateState = ReturnType<typeof useSkillUpdateState>;

type Callbacks = { onBack: () => void; onOpenReview: (skillId: string) => void; onChanged: () => void | Promise<void> };

/** Runs one request with the busy flag and the problem line; true when it succeeded. */
async function runAction(state: UpdateState, action: () => Promise<unknown>): Promise<boolean> {
  state.setBusy(true);
  state.setProblem(null);
  state.setMessage(null);
  try {
    await action();
    return true;
  } catch (error) {
    state.setProblem(refusalText(error));
    return false;
  } finally {
    state.setBusy(false);
  }
}

async function createUpdateDraft(state: UpdateState, skillId: string, onChanged: Callbacks["onChanged"], path?: string) {
  state.setBusy(true);
  state.setProblem(null);
  state.setMessage(null);
  try {
    await updateFromUpstream(skillId, path);
    state.setPathMissing(false);
    await onChanged();
  } catch (error) {
    const failure = updateFailure(error);
    if (failure === "path_missing") state.setPathMissing(true);
    if (failure === "up_to_date") state.setMessage(refusalText(error));
    else if (failure !== "draft_exists") state.setProblem(refusalText(error));
  } finally {
    state.setBusy(false);
    await state.reload();
  }
}

export function skillUpdateActions(state: UpdateState, skillId: string, { onBack, onOpenReview, onChanged }: Callbacks) {
  const { draft, report, reload } = state;
  const act = (action: () => Promise<unknown>) => runAction(state, action);
  return {
    createDraft: (path?: string) => createUpdateDraft(state, skillId, onChanged, path),
    resolve: async (conflictId: string, resolution: Resolution): Promise<boolean> => {
      if (!draft || !report) return false;
      const ok = await act(() => saveDraft(skillId, draft.version, { resolutions: withResolution(report, conflictId, resolution) }, draft.digest));
      await reload();
      return ok;
    },
    submit: async () => {
      if (!draft) return;
      if (await act(() => submitVersion(skillId, draft.version))) {
        await reload();
        await onChanged();
        onOpenReview(skillId);
      } else await reload();
    },
    discard: async () => {
      if (!draft) return;
      if (await act(() => retireVersion(skillId, draft.version))) {
        await onChanged();
        onBack();
      }
    },
  };
}
