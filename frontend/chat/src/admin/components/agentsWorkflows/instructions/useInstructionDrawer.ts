// The instruction drawer's state: the draft being edited, the stored instruction, its conflict findings and the
// governed lifecycle actions (save a draft, submit for review, publish).
import { useCallback, useEffect, useState, type Dispatch, type SetStateAction } from "react";

import type { ReadJsonFn } from "../../../hooks/useAdminTabLoader.types";
import { useApprovalRule } from "../../approvalRule/approvalRule";
import {
  INSTRUCTIONS_PATH, readFinding, readInstruction, tokenEstimate,
  type InstructionBinding, type InstructionFinding, type InstructionRow, type InstructionScope, type InstructionVersion,
} from "./instructionsModel";

export type Draft = {
  key: string;
  title: string;
  scopeType: InstructionScope;
  scopeId: string;
  binding: InstructionBinding;
  workflowKey: string;
  body: string;
};

function initialDraft(row: InstructionRow | null): Draft {
  return {
    key: row?.key ?? "",
    title: row?.title ?? "",
    scopeType: row?.scopeType ?? "global",
    scopeId: row?.scopeId ?? "",
    binding: row?.binding ?? "always",
    workflowKey: row?.workflowKey ?? "",
    body: row?.latest?.body ?? row?.published?.body ?? "",
  };
}

const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

async function runBusy(
  setBusy: Dispatch<SetStateAction<boolean>>, setProblem: Dispatch<SetStateAction<string | null>>, action: () => Promise<void>,
) {
  setBusy(true);
  setProblem(null);
  try {
    await action();
  } catch (error) {
    setProblem(error instanceof Error ? error.message : "The instruction could not be saved.");
  } finally {
    setBusy(false);
  }
}

type SaveContext = {
  readJson: ReadJsonFn; current: InstructionRow | null; draft: Draft; onChanged: () => void;
  setCurrent: Dispatch<SetStateAction<InstructionRow | null>>; setAccept: Dispatch<SetStateAction<boolean>>;
  refresh: (id: string) => Promise<InstructionRow>; check: (version: InstructionVersion | null) => Promise<void>;
};

// A new instruction is created with its first draft; a stored one gets a new draft version.
async function saveInstructionDraft({ readJson, current, draft, onChanged, setCurrent, setAccept, refresh, check }: SaveContext) {
  let detail: InstructionRow;
  if (!current) {
    detail = readInstruction(await readJson<unknown>(INSTRUCTIONS_PATH, post({
      key: draft.key.trim(), title: draft.title.trim(), scope_type: draft.scopeType,
      scope_id: draft.scopeType === "global" ? null : draft.scopeId || null, binding: draft.binding,
      workflow_key: draft.binding === "workflow" ? draft.workflowKey || null : null, body: draft.body,
    })));
    setCurrent(detail);
    onChanged();
  } else {
    await readJson<unknown>(`${INSTRUCTIONS_PATH}/${encodeURIComponent(current.id)}/drafts`, post({ body: draft.body }));
    detail = await refresh(current.id);
  }
  setAccept(false);
  await check(detail.latest);
}

export function useInstructionDrawer(row: InstructionRow | null, readJson: ReadJsonFn, onChanged: () => void) {
  const [current, setCurrent] = useState<InstructionRow | null>(row);
  const [draft, setDraft] = useState<Draft>(() => initialDraft(row));
  const [findings, setFindings] = useState<InstructionFinding[] | null>(row?.latest?.findings.length ? row.latest.findings : null);
  const [accept, setAccept] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const selfApprove = useApprovalRule().selfApprovalAllowed;
  const latest: InstructionVersion | null = current?.latest ?? null;
  const tokens = tokenEstimate(draft.body);
  const set = (patch: Partial<Draft>) => setDraft((value) => ({ ...value, ...patch }));

  const refresh = useCallback(async (id: string) => {
    const detail = readInstruction(await readJson<unknown>(`${INSTRUCTIONS_PATH}/${encodeURIComponent(id)}`));
    setCurrent(detail);
    onChanged();
    return detail;
  }, [onChanged, readJson]);

  const check = useCallback(async (version: InstructionVersion | null) => {
    if (!version || version.state !== "draft") return;
    const raw = await readJson<{ findings?: unknown[] }>(`${INSTRUCTIONS_PATH}/versions/${version.id}/conflicts`);
    setFindings((raw.findings ?? []).map(readFinding));
  }, [readJson]);

  useEffect(() => { void check(row?.latest ?? null).catch(() => undefined); }, [check, row]);

  const run = (action: () => Promise<void>) => runBusy(setBusy, setProblem, action);
  const saveDraft = () => run(() => saveInstructionDraft({ readJson, current, draft, onChanged, setCurrent, setAccept, refresh, check }));
  const submit = () => run(async () => {
    if (!current || !latest) return;
    await readJson<unknown>(`${INSTRUCTIONS_PATH}/versions/${latest.id}/submit`, post({ accept_findings: accept }));
    await refresh(current.id);
  });
  const publish = () => run(async () => {
    if (!current || !latest) return;
    await readJson<unknown>(`${INSTRUCTIONS_PATH}/versions/${latest.id}/publish`, post({ self_approve: selfApprove }));
    await refresh(current.id);
  });
  return { current, draft, set, findings, accept, setAccept, busy, problem, selfApprove, latest, tokens, saveDraft, submit, publish };
}

export type InstructionDrawerState = ReturnType<typeof useInstructionDrawer>;
