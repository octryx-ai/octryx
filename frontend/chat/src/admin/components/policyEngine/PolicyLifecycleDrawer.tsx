import { useEffect, useState } from "react";

import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import {
  approveReview, loadVersion, publishVersion, retireVersion, saveDraftNote, submitVersion,
} from "./policyEngineApi";
import { refusalText } from "./policyEngineVersions";
import type { PolicyVersion } from "./policyEngineVersions";
import { lineDiff, readHistory, readReview } from "./policyLifecycleModel";
import type { HistoryRow, Review } from "./policyLifecycleModel";
import type { PolicyItem } from "./policyCatalogModel";
import { LifecycleChanges, LifecycleChecks, LifecycleHistory, LifecycleReview, LifecycleTimeline } from "./PolicyLifecycleParts";
import "./policyDrawers.css";

type Act = (action: () => Promise<unknown>, done: string) => Promise<void>;

// Discard or withdraw, Close, and the next step: publish (single admin), submit, or approve and publish.
function LifecycleFooter({ working, state, busy, oneStep, review, act, submit, publishOwn, onClose }: {
  working: PolicyVersion | null;
  state: string | null;
  busy: boolean;
  oneStep: boolean;
  review: Review | null;
  act: Act;
  submit: () => Promise<void>;
  publishOwn: () => Promise<void>;
  onClose: () => void;
}) {
  return (
    <>
      {working ? <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger" data-testid="lifecycle-discard" disabled={busy}
        onClick={() => void act(() => retireVersion(working.version), `Version ${working.version} withdrawn.`)}>{state === "in_review" ? "Withdraw" : "Discard draft"}</button> : null}
      <span className="policies__spacer" />
      <button type="button" className="admin-panel__action-btn" onClick={onClose}>Close</button>
      {oneStep ? <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="lifecycle-publish-own" disabled={busy} onClick={() => void publishOwn()}>Publish</button> : null}
      {state === "draft" && !oneStep ? <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="lifecycle-submit" disabled={busy} onClick={() => void submit()}>Submit for review</button> : null}
      {state === "in_review" && !oneStep ? (
        <>
          <button type="button" className="admin-panel__action-btn" data-testid="lifecycle-approve" disabled={busy || !review?.viewer.canApprove}
            title={review && !review.viewer.canApprove ? "Four-eyes: another platform admin approves." : undefined}
            onClick={() => void act(() => approveReview(working!.approvalId!), "Review approved.")}>Approve</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="lifecycle-publish" disabled={busy || review?.status !== "approved"}
            onClick={() => void act(() => publishVersion(working!.version, working!.approvalId), `Version ${working!.version} published.`)}>Publish</button>
        </>
      ) : null}
    </>
  );
}

// Every lifecycle action is busy while it runs and shows the refusal; submit saves a changed note first, and the
// single-admin publish submits a draft before publishing it as self-approved.
function lifecycleActions({ working, state, note, onChanged, setBusy, setProblem }: {
  working: PolicyVersion | null;
  state: string | null;
  note: string;
  onChanged: (message: string) => Promise<void>;
  setBusy: (busy: boolean) => void;
  setProblem: (problem: string | null) => void;
}) {
  const act = async (action: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setProblem(null);
    try {
      await action();
      await onChanged(done);
    } catch (error) {
      setProblem(refusalText(error));
    } finally {
      setBusy(false);
    }
  };
  const submit = () => act(async () => {
    if (working && note !== (working.note ?? "")) await saveDraftNote(working.version, note);
    await submitVersion(working!.version);
  }, "Submitted: another platform admin must approve it.");
  const publishOwn = () => act(async () => {
    if (working && state === "draft") {
      if (note !== (working.note ?? "")) await saveDraftNote(working.version, note);
      await submitVersion(working.version);
    }
    await publishVersion(working!.version, null, true);
  }, `Version ${working?.version} published (self-approved).`);
  return { act, submit, publishOwn };
}

// The lifecycle of the custom policy set: Draft → In review (four-eyes) → Published, the
// changes against the published version with the Cedar diff, the checks and the change note, the review from the
// viewer's side, and the version history with roll back. The store's rules are unchanged: submitting freezes the
// text, publishing needs another platform admin's approval and passing test cases, rollback creates a new draft.
// Under the single-admin approval rule (`selfApproval`) the author publishes in one step: submit + self-approve.
export function PolicyLifecycleDrawer({ working, published, items, history, schemaVersion, selfApproval = false, onChanged, onClose }: {
  working: PolicyVersion | null;
  published: PolicyVersion | null;
  items: PolicyItem[];
  history: unknown;
  schemaVersion: string;
  selfApproval?: boolean;
  onChanged: (message: string) => Promise<void>;
  onClose: () => void;
}) {
  const [review, setReview] = useState<Review | null>(null);
  const [note, setNote] = useState(working?.note ?? "");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const rows: HistoryRow[] = readHistory(history);
  const state = working?.state ?? null;
  const changes = items.filter((item) => item.change && item.change !== "unchanged");
  const diff = working ? lineDiff(published?.policies ?? "", working.policies ?? "") : null;

  useEffect(() => {
    let alive = true;
    if (working?.state === "in_review") void loadVersion(working.version).then((raw) => { if (alive) setReview(readReview(raw)); }).catch(() => undefined);
    return () => { alive = false; };
  }, [working?.version, working?.state]);

  const { act, submit, publishOwn } = lifecycleActions({ working, state, note, onChanged, setBusy, setProblem });
  const oneStep = selfApproval && (state === "draft" || (state === "in_review" && review?.status !== "approved"));

  const title = working ? `${state === "in_review" ? "In review" : "Draft"} v${working.version}` : "Version history";
  const footer = <LifecycleFooter working={working} state={state} busy={busy} oneStep={oneStep} review={review} act={act}
    submit={submit} publishOwn={publishOwn} onClose={onClose} />;

  return (
    <SettingsDrawer eyebrow="Policy set · lifecycle" title={title} size="detail" onClose={onClose} footer={footer}>
      <div data-testid="policy-lifecycle" className="policies__pane">
        {working ? <LifecycleTimeline state={state} changes={changes} selfApproval={selfApproval} published={published} /> : null}
        {problem ? <p className="workspace-classification__message" role="alert" data-testid="lifecycle-problem">{problem}</p> : null}
        {working ? <LifecycleChanges changes={changes} published={published} diff={diff} /> : null}
        {working ? (
          <LifecycleChecks working={working} schemaVersion={schemaVersion} state={state} note={note} setNote={setNote}
            selfApproval={selfApproval} />
        ) : null}
        {state === "in_review" && review ? <LifecycleReview review={review} /> : null}
        <LifecycleHistory rows={rows} busy={busy} act={act} />
      </div>
    </SettingsDrawer>
  );
}
