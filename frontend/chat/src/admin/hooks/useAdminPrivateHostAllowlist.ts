import { useCallback, useEffect, useState } from "react";
import {
  loadPrivateHostAllowlist,
  savePrivateHostEntries,
} from "../components/connectorsTab/privateHostAllowlistApi";
import {
  addEntry,
  applyRefusal,
  draftFromEntries,
  entriesOf,
  removeEntry,
  type PrivateHostDraft,
} from "../components/connectorsTab/privateHostAllowlistModel";

export type PrivateHostAllowlistState = {
  drafts: PrivateHostDraft[];
  loading: boolean;
  loadError: string | null;
  inputs: Record<string, string>;
  inputRefusals: Record<string, string | null>;
  savingConnection: string | null;
  reload: () => Promise<void>;
  setInput: (connection: string, value: string) => void;
  add: (connection: string) => void;
  remove: (connection: string, rowKey: string) => void;
  discard: (connection: string) => void;
  save: (connection: string) => Promise<void>;
};

export function useAdminPrivateHostAllowlist(): PrivateHostAllowlistState {
  const [drafts, setDrafts] = useState<PrivateHostDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [inputRefusals, setInputRefusals] = useState<
    Record<string, string | null>
  >({});
  const [savingConnection, setSavingConnection] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    const outcome = await loadPrivateHostAllowlist();
    if (outcome.ok) {
      setDrafts(outcome.drafts);
      setLoadError(null);
    } else {
      setLoadError(outcome.code);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const updateDraft = (
    connection: string,
    change: (draft: PrivateHostDraft) => PrivateHostDraft,
  ) => {
    setDrafts((current) =>
      current.map((draft) =>
        draft.connection === connection ? change(draft) : draft,
      ),
    );
  };

  const setInput = (connection: string, value: string) => {
    setInputs((current) => ({ ...current, [connection]: value }));
    setInputRefusals((current) => ({ ...current, [connection]: null }));
  };

  const add = (connection: string) => {
    const draft = drafts.find((item) => item.connection === connection);
    if (!draft) return;
    const result = addEntry(draft, inputs[connection] ?? "");
    if (!result.ok) {
      setInputRefusals((current) => ({
        ...current,
        [connection]: result.reason,
      }));
      return;
    }
    updateDraft(connection, () => result.draft);
    setInputs((current) => ({ ...current, [connection]: "" }));
  };

  const remove = (connection: string, rowKey: string) => {
    updateDraft(connection, (draft) => removeEntry(draft, rowKey));
  };

  const discard = (connection: string) => {
    updateDraft(connection, (draft) =>
      draftFromEntries(connection, draft.saved),
    );
    setInputRefusals((current) => ({ ...current, [connection]: null }));
  };

  const save = async (connection: string) => {
    const draft = drafts.find((item) => item.connection === connection);
    if (!draft || savingConnection) return;
    setSavingConnection(connection);
    try {
      const outcome = await savePrivateHostEntries(
        connection,
        entriesOf(draft),
      );
      if (outcome.ok) {
        updateDraft(connection, () =>
          draftFromEntries(connection, outcome.entries),
        );
      } else {
        updateDraft(connection, (current) =>
          applyRefusal(current, outcome.refusal),
        );
      }
    } finally {
      setSavingConnection(null);
    }
  };

  return {
    drafts,
    loading,
    loadError,
    inputs,
    inputRefusals,
    savingConnection,
    reload,
    setInput,
    add,
    remove,
    discard,
    save,
  };
}
