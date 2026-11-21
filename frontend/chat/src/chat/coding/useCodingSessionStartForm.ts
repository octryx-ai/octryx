// The start dialog's form: the work item picked, the request and the scope fields, and the plan request it sends.
import { useEffect, useMemo, useState } from "react";

import type { WorkItem } from "../work/workItemTypes";
import { createCodingSessionPlan } from "./codingSessionPlanRequest";
import {
  START_DIALOG_COPY,
  defaultIntent,
  filterStartCandidates,
  sortStartCandidates,
  splitLines,
  startListMessage,
} from "./codingStartCandidates";

export function useCodingSessionStartForm(open: boolean, items: WorkItem[]) {
  const sortedItems = useMemo(() => sortStartCandidates(items), [items]);
  const [search, setSearch] = useState("");
  const [selectedItemId, setSelectedItemId] = useState("");
  const [intent, setIntent] = useState("");
  const [intentTouched, setIntentTouched] = useState(false);
  const [repositoryInput, setRepositoryInput] = useState("");
  const [branchInput, setBranchInput] = useState("");
  const [plannedFilesInput, setPlannedFilesInput] = useState("");
  const [validationInput, setValidationInput] = useState("");
  const [rollbackPlan, setRollbackPlan] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedItem = sortedItems.find((item) => item.id === selectedItemId) || null;
  const filteredItems = useMemo(() => filterStartCandidates(sortedItems, search), [search, sortedItems]);
  const listMessage = startListMessage(sortedItems.length, filteredItems.length);

  useEffect(() => {
    if (open && !selectedItemId && sortedItems[0]) {
      setSelectedItemId(sortedItems[0].id);
    }
  }, [open, selectedItemId, sortedItems]);

  useEffect(() => {
    if (!selectedItem || intentTouched) {
      return;
    }
    setIntent(defaultIntent(selectedItem));
  }, [intentTouched, selectedItem]);

  return {
    sortedItems, filteredItems, listMessage, selectedItem, search, setSearch, selectedItemId, setSelectedItemId,
    intent, setIntent, setIntentTouched, repositoryInput, setRepositoryInput, branchInput, setBranchInput,
    plannedFilesInput, setPlannedFilesInput, validationInput, setValidationInput, rollbackPlan, setRollbackPlan,
    saving, setSaving, error, setError,
  };
}

export type CodingSessionStartForm = ReturnType<typeof useCodingSessionStartForm>;

function resetStartForm(form: CodingSessionStartForm) {
  form.setSearch("");
  form.setIntentTouched(false);
  form.setRepositoryInput("");
  form.setBranchInput("");
  form.setPlannedFilesInput("");
  form.setValidationInput("");
  form.setRollbackPlan("");
  form.setError(null);
}

// Sends the change plan for the picked item; the form clears after it was created.
export async function submitStartForm(form: CodingSessionStartForm, onCreated: (workItemId: string) => void) {
  const { selectedItem, sortedItems, setError, setSaving } = form;
  if (!selectedItem) {
    setError(sortedItems.length === 0 ? START_DIALOG_COPY.noItems : "Select a work item first.");
    return;
  }
  const repositories = splitLines(form.repositoryInput);
  if (repositories.length === 0) {
    setError("Add at least one repository. A coding session needs an explicit repository scope.");
    return;
  }
  const validationCommands = splitLines(form.validationInput);
  const branchHints = splitLines(form.branchInput);
  const plannedFiles = splitLines(form.plannedFilesInput);
  setSaving(true);
  setError(null);
  try {
    await createCodingSessionPlan({
      selectedItem,
      repositories,
      branchHints,
      plannedFiles,
      validationCommands,
      intent: form.intent,
      rollbackPlan: form.rollbackPlan,
    });
    onCreated(selectedItem.id);
    resetStartForm(form);
  } catch (err) {
    setError(err instanceof Error ? err.message : "Failed to create the change plan");
  } finally {
    setSaving(false);
  }
}
