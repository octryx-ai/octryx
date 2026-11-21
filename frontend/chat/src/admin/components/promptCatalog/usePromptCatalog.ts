// State of the prompt catalog tab: the key list, and one key's detail with its lifecycle actions.
// Every action reloads the detail and the list; a refusal is kept as coded text, never swallowed.
import { useCallback, useEffect, useState } from "react";
import { promptCatalogApi, type PromptCatalogApi } from "./promptCatalogApi";
import { approvalModeHistoryText } from "../approvalRule/approvalRule";
import { describePromptRefusal, type PromptRefusal } from "./promptCatalogModel";
import type { PromptDetail, PromptDiff, PromptListItem, PromptPublishResult, PromptVersionState } from "./promptCatalogTypes";

export function usePromptCatalogList(api: PromptCatalogApi = promptCatalogApi) {
  const [items, setItems] = useState<PromptListItem[] | null>(null);
  const [refusal, setRefusal] = useState<PromptRefusal | null>(null);
  // null: the prompt areas; a collapsed area (tool / MCP descriptions) is loaded on request.
  const [area, setArea] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<{ area: string; count: number }[]>([]);

  const reload = useCallback(async () => {
    try {
      const response = await api.list(area ?? undefined);
      setItems(response.items);
      setCollapsed(response.collapsed_areas.map((name) => ({ area: name, count: response.areas[name] ?? 0 })));
      setRefusal(null);
    } catch (error) {
      setRefusal(describePromptRefusal(error));
    }
  }, [api, area]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { items, refusal, reload, area, setArea, collapsed };
}

export type PromptBusy = "load" | "diff" | "submit" | "decide" | "publish" | "retire" | null;

export function usePromptDetail(key: string, onChanged: () => void, api: PromptCatalogApi = promptCatalogApi) {
  const [detail, setDetail] = useState<PromptDetail | null>(null);
  const [diff, setDiff] = useState<PromptDiff | null>(null);
  const [busy, setBusy] = useState<PromptBusy>("load");
  const [refusal, setRefusal] = useState<PromptRefusal | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setDetail(await api.get(key));
    } catch (error) {
      setRefusal(describePromptRefusal(error));
    } finally {
      setBusy(null);
    }
  }, [api, key]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const run = useCallback(
    <T>(kind: Exclude<PromptBusy, "load" | null>, action: () => Promise<T>, done: string | ((result: T) => string)) =>
      runPromptAction({ setBusy, setRefusal, setNotice, reload, onChanged }, kind, action, done),
    [onChanged, reload],
  );

  const showDiff = useCallback(
    async (versionId: string) => {
      setBusy("diff");
      setRefusal(null);
      try {
        setDiff(await api.diff(versionId));
      } catch (error) {
        setRefusal(describePromptRefusal(error));
      } finally {
        setBusy(null);
      }
    },
    [api],
  );

  return {
    detail,
    diff,
    busy,
    refusal,
    notice,
    reload,
    showDiff,
    clearDiff: () => setDiff(null),
    clearMessages: () => {
      setRefusal(null);
      setNotice(null);
    },
    ...promptLifecycleActions(api, run, reload),
  };
}

type RunAction = <T>(
  kind: Exclude<PromptBusy, "load" | null>,
  action: () => Promise<T>,
  done: string | ((result: T) => string),
) => Promise<boolean>;

type RunSetters = {
  setBusy: (busy: PromptBusy) => void;
  setRefusal: (refusal: PromptRefusal | null) => void;
  setNotice: (notice: string | null) => void;
  reload: () => Promise<void>;
  onChanged: () => void;
};

// One lifecycle action: busy while it runs, its notice on success (then the detail and the list reload), the coded
// refusal otherwise. Returns whether it succeeded.
async function runPromptAction<T>(
  { setBusy, setRefusal, setNotice, reload, onChanged }: RunSetters,
  kind: Exclude<PromptBusy, "load" | null>,
  action: () => Promise<T>,
  done: string | ((result: T) => string),
): Promise<boolean> {
  setBusy(kind);
  setRefusal(null);
  setNotice(null);
  try {
    const result = await action();
    setNotice(typeof done === "string" ? done : done(result));
    await reload();
    onChanged();
    return true;
  } catch (error) {
    setRefusal(describePromptRefusal(error));
    return false;
  } finally {
    setBusy(null);
  }
}

// The lifecycle actions of one key's versions, each run through `run` with the notice it shows.
function promptLifecycleActions(api: PromptCatalogApi, run: RunAction, reload: () => Promise<void>) {
  return {
    submit: (versionId: string) =>
      run("submit", () => api.submit(versionId), "Submitted: another person who may change this scope approves it from their Inbox."),
    publish: (versionId: string, approvalId: string | null) =>
      run("publish", () => api.publish(versionId, approvalId), publishedNotice),
    // Single-admin approval rule: submit a draft for review, then approve the own review and publish in one step.
    // A refused publish after a successful submit leaves the version in review: reload to show it.
    publishSelfApproved: async (versionId: string, state: PromptVersionState) => {
      const published = await run(
        "publish",
        async () => {
          if (state === "draft") await api.submit(versionId);
          return api.publish(versionId, null, true);
        },
        publishedNotice,
      );
      if (!published && state === "draft") await reload();
      return published;
    },
    approve: (approvalId: string) =>
      run("decide", () => api.approve(approvalId), "Approved: publish it now, or the author publishes it."),
    reject: (approvalId: string) =>
      run("decide", () => api.reject(approvalId, "Rejected in the prompt editor"), "Rejected: the author can write a new draft."),
    retire: (versionId: string) => run("retire", () => api.retire(versionId), "Retired."),
    revert: (key: string) =>
      run("publish", () => api.revert(key), "Reverted: the next turn uses the shipped text again."),
  };
}

const publishedNotice = (result: PromptPublishResult) => {
  const mode = approvalModeHistoryText(result.approval_gate?.approval_mode);
  return `Published${mode ? ` (${mode})` : ""}: the next turn uses this version.`;
};

export type PromptDetailModel = ReturnType<typeof usePromptDetail>;
