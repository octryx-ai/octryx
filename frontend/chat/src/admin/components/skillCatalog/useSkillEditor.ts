import { useCallback, useEffect, useMemo, useState } from "react";

import { createSkill, editSkill, loadSkill, saveDraft, saveTags, submitVersion } from "./skillCatalogApi";
import { refusalText } from "./skillCatalogModel";
import type { SkillDetail, SkillVersion } from "./skillCatalogTypes";
import { blockingIssues, buildFrontmatter, createBody, editorChecks, emptyForm, formFromVersion, saveBody, skillMdText, tagList } from "./skillEditorModel";
import type { EditorBase, EditorForm } from "./skillEditorModel";

export type Loaded = { version: SkillVersion | null; base: EditorBase | null; tags: string[]; created: boolean; frozen: boolean };

function errorCode(error: unknown): string {
  return error && typeof error === "object" && typeof (error as { code?: unknown }).code === "string" ? (error as { code: string }).code : "";
}

// The editor's state: the form, the draft it started from (a draft in review loads frozen), the live checks and
// the SKILL.md preview.
export function useSkillEditor(skillId: string | null) {
  const isNew = skillId === null;
  const [form, setForm] = useState<EditorForm>(emptyForm);
  const [loaded, setLoaded] = useState<Loaded | null>(isNew ? { version: null, base: null, tags: [], created: false, frozen: false } : null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async (id: string): Promise<void> => {
    const detail = (await loadSkill(id)) as SkillDetail;
    if (detail.open?.state === "in_review") {
      const { form: next, base } = formFromVersion(detail.open, detail.tags);
      setForm(next);
      setLoaded({ version: detail.open, base, tags: detail.tags, created: false, frozen: true });
      return;
    }
    const response = (await editSkill(id)) as SkillVersion & { created?: boolean };
    const { form: next, base } = formFromVersion(response, detail.tags);
    setForm(next);
    setLoaded({ version: response, base, tags: detail.tags, created: Boolean(response.created), frozen: false });
  }, []);

  useEffect(() => {
    if (!skillId) return;
    let alive = true;
    load(skillId).catch((error) => { if (alive) setProblem(refusalText(error)); });
    return () => { alive = false; };
  }, [skillId, load]);

  const base = loaded?.base ?? null;
  const checks = useMemo(() => editorChecks(form, base), [form, base]);
  const skillMd = useMemo(() => skillMdText(buildFrontmatter(form, base), form.body), [form, base]);
  const patch = (change: Partial<EditorForm>) => setForm((current) => ({ ...current, ...change }));
  return { isNew, form, loaded, setLoaded, busy, setBusy, problem, setProblem, load, base, checks, skillMd, patch };
}

type Editor = ReturnType<typeof useSkillEditor>;
type Callbacks = { onSaved: (skillId: string) => void; onOpenReview: (skillId: string) => void };

/** Save the form; returns the skill id and the saved version number. */
async function persist(editor: Editor, skillId: string | null, loaded: Loaded): Promise<{ id: string; version: number } | null> {
  const { form, base, setLoaded, setProblem, isNew } = editor;
  const version = loaded.version;
  const issues = blockingIssues(form, isNew);
  if (issues.length) {
    setProblem(issues.join(" "));
    return null;
  }
  if (!skillId || !version || !base) {
    const created = (await createSkill(createBody(form))) as SkillVersion & { skill_id: string };
    return { id: created.skill_id, version: created.version };
  }
  const saved = (await saveDraft(skillId, version.version, saveBody(form, base), version.digest)) as SkillVersion;
  const next = formFromVersion(saved, loaded.tags);
  setLoaded({ ...loaded, version: saved, base: next.base });
  const tags = tagList(form);
  if (tags.join(",") !== loaded.tags.join(",")) {
    await saveTags(skillId, tags);
    setLoaded((current) => (current ? { ...current, tags } : current));
  }
  return { id: skillId, version: saved.version };
}

// Save (and optionally submit for review); a draft conflict reloads the draft the server has.
export async function runSkillEditorSave(editor: Editor, skillId: string | null, loaded: Loaded, submit: boolean, { onSaved, onOpenReview }: Callbacks) {
  const { setBusy, setProblem, isNew, load } = editor;
  setBusy(true);
  setProblem(null);
  try {
    const saved = await persist(editor, skillId, loaded);
    if (!saved) return;
    if (!submit) {
      onSaved(saved.id);
      return;
    }
    try {
      await submitVersion(saved.id, saved.version);
    } catch (error) {
      // A new skill exists now: continue on its page (the draft is saved, only the submit was refused).
      if (isNew) {
        onSaved(saved.id);
        return;
      }
      throw error;
    }
    onOpenReview(saved.id);
  } catch (error) {
    setProblem(refusalText(error));
    if (errorCode(error) === "skill_draft_conflict" && skillId) {
      await load(skillId).catch((reloadError) => setProblem(refusalText(reloadError)));
    }
  } finally {
    setBusy(false);
  }
}
