import { useCallback, useState } from "react";

import type { LiveIssue } from "./cedarValidation";
import { createDraft, loadVersion, saveDraft, validatePolicies } from "./policyEngineApi";
import { readIssues, readVersion, refusalText } from "./policyEngineVersions";
import type { PolicyIssue, PolicyVersion } from "./policyEngineVersions";

export type Message = { ok: boolean; text: string };

const CONFLICT = "policy_set_draft_conflict";
const isConflict = (error: unknown) => (error as { code?: unknown } | null)?.code === CONFLICT;

// The editor's state: the text and note (from the working draft, else the published set), the server's issues,
// the live issues, the digest the text started from and a save conflict.
export function useCedarSet(published: PolicyVersion | null, working: PolicyVersion | null, initialDiff: boolean) {
  const [text, setText] = useState(working?.policies ?? published?.policies ?? "");
  const [note, setNote] = useState(working?.note ?? "");
  const [issues, setIssues] = useState<PolicyIssue[]>([]);
  const [live, setLive] = useState<LiveIssue[] | null>(null);
  const [showDiff, setShowDiff] = useState(initialDiff);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<Message | null>(null);
  const [base, setBase] = useState(working?.digest ?? "");
  const [conflict, setConflict] = useState<PolicyVersion | null>(null);
  const onLiveIssues = useCallback((next: LiveIssue[] | null) => setLive(next), []);
  return {
    text, setText, note, setNote, issues, setIssues, live, showDiff, setShowDiff, busy, setBusy, message, setMessage, base, setBase,
    conflict, setConflict, onLiveIssues,
  };
}

type CedarSet = ReturnType<typeof useCedarSet>;

// Validate, save (with If-Match; a conflict keeps this text and loads theirs for the choice) and load theirs.
export function cedarSetActions(state: CedarSet, working: PolicyVersion | null, onChanged: () => Promise<void>) {
  const { text, note, base, conflict, setBusy, setMessage, setIssues, setBase, setConflict, setText, setNote } = state;
  const run = async (action: () => Promise<unknown>, done: string, rethrowConflict = false) => {
    setBusy(true);
    setMessage(null);
    try {
      await action();
      await onChanged();
      setMessage({ ok: true, text: done });
    } catch (error) {
      if (rethrowConflict && isConflict(error)) throw error;
      setMessage({ ok: false, text: refusalText(error) });
    } finally {
      setBusy(false);
    }
  };

  const validate = async () => {
    setBusy(true);
    try {
      const answer = await validatePolicies(text) as { valid?: unknown };
      setIssues(readIssues(answer));
      setMessage(answer.valid === true ? { ok: true, text: "The server accepts these policies." } : { ok: false, text: "The server refuses these policies." });
      return answer.valid === true;
    } catch (error) {
      setMessage({ ok: false, text: refusalText(error) });
      return false;
    } finally {
      setBusy(false);
    }
  };

  const save = async (etag: string = base) => {
    if (!(await validate())) return;
    setConflict(null);
    try {
      await run(async () => {
        const saved = readVersion(await (working?.state === "draft"
          ? saveDraft(working.version, text, note, etag) : createDraft(text, note)));
        if (saved) setBase(saved.digest);
      }, "Draft saved; the saved test cases ran against it.", true);
    } catch (error) {
      if (!isConflict(error) || !working) throw error;
      setConflict(readVersion(await loadVersion(working.version).catch(() => null)));
      setMessage({ ok: false, text: refusalText(error) });
    }
  };

  const loadTheirs = () => {
    if (!conflict) return;
    setText(conflict.policies ?? "");
    setNote(conflict.note ?? "");
    setBase(conflict.digest);
    setConflict(null);
    setMessage(null);
    void onChanged();
  };
  return { validate, save, loadTheirs };
}
