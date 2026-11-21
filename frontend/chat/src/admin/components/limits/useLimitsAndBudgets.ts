// The limits page's state: the stored limits and their drafts, the overview (overrides, environment limits, budgets),
// the open overrides list and budget, and the save of the limits only.
import { useCallback, useEffect, useState, type Dispatch, type SetStateAction } from "react";

import { readJson } from "../../utils/adminPanelHelpers";
import { draftsFromSettings, limitsPayload, readOverview } from "./limitsContract";
import type { Budget, Overview } from "./limitsContract";

const SETTINGS = "/admin/chat/api/panel/runtime-settings";
const OVERVIEW = "/api/v1/admin/limits/overview";

type Message = { error: boolean; text: string } | null;
type Setter<T> = Dispatch<SetStateAction<T>>;

async function saveLimits(
  drafts: Record<string, string>, stored: Record<string, string> | null, setStored: Setter<Record<string, string> | null>,
  setDrafts: Setter<Record<string, string>>, setMessage: Setter<Message>, setSaving: Setter<boolean>,
) {
  if (!stored) return;
  const built = limitsPayload(drafts, stored);
  if ("error" in built) {
    setMessage({ error: true, text: built.error });
    return;
  }
  setSaving(true);
  setMessage(null);
  try {
    const saved = draftsFromSettings(await readJson<Record<string, unknown>>(SETTINGS, {
      method: "PUT", body: JSON.stringify(built.payload),
    }));
    setStored(saved);
    setDrafts(saved);
    setMessage({ error: false, text: "Saved: limits only." });
  } catch (failure) {
    setMessage({ error: true, text: `Not saved: ${failure instanceof Error ? failure.message : "the change was refused"}.` });
  } finally {
    setSaving(false);
  }
}

export function useLimitsAndBudgets() {
  const [stored, setStored] = useState<Record<string, string> | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [overview, setOverview] = useState<Overview | null>(null);
  const [message, setMessage] = useState<Message>(null);
  const [saving, setSaving] = useState(false);
  const [openOverrides, setOpenOverrides] = useState("");
  const [budget, setBudget] = useState<Budget | "new" | null>(null);

  const reloadOverview = useCallback(() => {
    readJson<unknown>(OVERVIEW).then((payload) => setOverview(readOverview(payload))).catch(() => setOverview(null));
  }, []);
  useEffect(() => {
    readJson<Record<string, unknown>>(SETTINGS)
      .then((settings) => {
        const read = draftsFromSettings(settings);
        setStored(read);
        setDrafts(read);
      })
      .catch(() => setMessage({ error: true, text: "The limits could not be loaded (platform admin role required)." }));
    reloadOverview();
  }, [reloadOverview]);

  const save = () => saveLimits(drafts, stored, setStored, setDrafts, setMessage, setSaving);
  return {
    stored, drafts, setDrafts, overview, message, saving, openOverrides, setOpenOverrides, budget, setBudget, reloadOverview, save,
  };
}

export type LimitsPage = ReturnType<typeof useLimitsAndBudgets>;
