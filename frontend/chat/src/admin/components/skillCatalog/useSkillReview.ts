import { useCallback, useEffect, useState } from "react";

import { useApprovalRule } from "../approvalRule/approvalRule";
import { approveReview, loadDiff, loadSkill, publishVersion, rejectReview, saveDraft, submitVersion } from "./skillCatalogApi";
import { refusalText } from "./skillCatalogModel";
import type { FileDiff } from "./skillDiffModel";
import type { SkillDetail } from "./skillCatalogTypes";
import { changedFiles } from "./skillUpdateModel";

// The review drawer's state: the skill (reloaded after every action), the diff of its open version against the
// published one, the reviewer note and the approval rule.
export function useSkillReview(skillId: string) {
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [diff, setDiff] = useState<FileDiff[] | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const selfApproval = useApprovalRule().selfApprovalAllowed;

  const reload = useCallback(async () => {
    try {
      const next = (await loadSkill(skillId)) as SkillDetail;
      setDetail(next);
      setNote(next.open?.note ?? "");
    } catch (error) {
      setProblem(refusalText(error));
    }
  }, [skillId]);

  useEffect(() => { void reload(); }, [reload]);

  const version = detail?.open ?? null;
  const shownVersion = version?.version ?? null;
  const shownDigest = version?.digest ?? "";
  useEffect(() => {
    let alive = true;
    if (shownVersion === null) return undefined;
    loadDiff(skillId, shownVersion, "published")
      .then((raw) => { if (alive) setDiff(changedFiles(((raw as { files?: FileDiff[] }).files) ?? [])); })
      .catch((error) => { if (alive) setProblem(refusalText(error)); });
    return () => { alive = false; };
  }, [skillId, shownVersion, shownDigest]);

  return { detail, diff, note, setNote, busy, setBusy, problem, setProblem, done, setDone, selfApproval, reload, version };
}

type Review = ReturnType<typeof useSkillReview>;

// The lifecycle actions; each one reports its outcome, then reloads the skill and tells the page.
export function skillReviewActions(state: Review, skillId: string, onChanged: () => void) {
  const { note, setBusy, setProblem, setDone, reload, version } = state;
  const review = state.detail?.review ?? null;
  const act = async (action: () => Promise<unknown>, message: string) => {
    setBusy(true);
    setProblem(null);
    setDone(null);
    try {
      await action();
      setDone(message);
    } catch (error) {
      setProblem(refusalText(error));
    } finally {
      setBusy(false);
      await reload();
      onChanged();
    }
  };

  const submit = () => act(async () => {
    if (!version) return;
    if (note.trim() !== (version.note ?? "").trim()) await saveDraft(skillId, version.version, { note: note.trim() || null }, version.digest);
    await submitVersion(skillId, version.version);
  }, "Submitted: another platform admin must approve it.");
  const approve = () => act(() => approveReview(review!.approval_id), "Review approved; the version can be published now.");
  const publish = () => act(() => publishVersion(skillId, version!.version, version!.approval_id ?? review!.approval_id),
    `v${version!.version} published.`);
  const reject = (reason: string) => act(() => rejectReview(review!.approval_id, reason), "Review rejected.");
  const publishOwn = () => act(async () => {
    if (!version) return;
    if (version.state === "draft") {
      if (note.trim() !== (version.note ?? "").trim()) await saveDraft(skillId, version.version, { note: note.trim() || null }, version.digest);
      await submitVersion(skillId, version.version);
    }
    await publishVersion(skillId, version.version, null, true);
  }, `v${version?.version} published (self-approved).`);
  return { run: { submit, approve, publish, publish_own: publishOwn }, reject };
}
