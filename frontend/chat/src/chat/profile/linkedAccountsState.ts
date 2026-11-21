// State and actions of the linked accounts panel: load, save (by id or found by email), verify and unlink.
import { useCallback, useEffect, useState } from "react";

import { loadLinkedAccounts, removeLinkedAccount, saveLinkedAccount, verifyLinkedAccount } from "./linkedAccountsApi";
import { linkedAccountErrorText, readLinkedAccount, readLinkedAccounts } from "./linkedAccountsModel";
import type { LinkedAccount, LinkedAccounts, LinkedPlatform } from "./linkedAccountsModel";

export type Editing = { platform: string; mode: "identifier" | "email"; value: string };

export function useLinkedAccountsState(userId: string) {
  const [data, setData] = useState<LinkedAccounts | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [workspaceId, setWorkspaceId] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmUnlink, setConfirmUnlink] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const loaded = readLinkedAccounts(await loadLinkedAccounts(userId));
      setData(loaded);
      setProblem(loaded ? null : "The server's answer was not a list of linked accounts.");
      setWorkspaceId((current) => current || loaded?.workspaces[0]?.id || "");
    } catch (error) {
      setProblem(linkedAccountErrorText(error));
    }
  }, [userId]);

  useEffect(() => {
    void load();
  }, [load]);

  return {
    userId, data, setData, problem, setProblem, notice, setNotice, editing, setEditing, workspaceId, setWorkspaceId,
    busy, setBusy, confirmUnlink, setConfirmUnlink,
  };
}

export type LinkedAccountsState = ReturnType<typeof useLinkedAccountsState>;

function replaceAccount(state: LinkedAccountsState, account: LinkedAccount | null, removedPlatform?: string) {
  state.setData((current) => {
    if (!current) return current;
    const others = current.accounts.filter(
      (item) => item.platform !== (account?.platform ?? removedPlatform),
    );
    return { ...current, accounts: account ? [...others, account] : others };
  });
}

async function runAccountAction(state: LinkedAccountsState, key: string, action: () => Promise<string | null>) {
  state.setBusy(key);
  state.setProblem(null);
  state.setNotice(null);
  try {
    state.setNotice(await action());
  } catch (error) {
    state.setProblem(linkedAccountErrorText(error));
  } finally {
    state.setBusy(null);
  }
}

export function saveAccount(state: LinkedAccountsState, platform: LinkedPlatform) {
  const { editing, workspaceId, userId } = state;
  if (!editing) return;
  const value = editing.value.trim();
  if (!value) return;
  if (editing.mode === "email" && !workspaceId) {
    state.setProblem("Choose the Workspace whose Jira Cloud connection finds the account.");
    return;
  }
  void runAccountAction(state, `save:${platform.platform}`, async () => {
    const body = editing.mode === "email" ? { email: value, project_id: workspaceId } : { identifier: value };
    const answer = (await saveLinkedAccount(userId, platform.platform, body)) as { account?: unknown };
    replaceAccount(state, readLinkedAccount(answer.account));
    state.setEditing(null);
    return editing.mode === "email" ? `${platform.label} account found and linked.` : `${platform.label} account saved.`;
  });
}

export function verifyAccount(state: LinkedAccountsState, account: LinkedAccount) {
  if (!state.workspaceId) {
    state.setProblem("Choose the Workspace whose connection checks the account.");
    return;
  }
  void runAccountAction(state, `verify:${account.platform}`, async () => {
    const answer = (await verifyLinkedAccount(state.userId, account.platform, state.workspaceId)) as { account?: unknown };
    const next = readLinkedAccount(answer.account);
    replaceAccount(state, next);
    return next?.verificationStatus === "verified"
      ? `${account.label} account verified.`
      : `The Workspace's connection does not know this ${account.label} account.`;
  });
}

export function unlinkAccount(state: LinkedAccountsState, account: LinkedAccount) {
  void runAccountAction(state, `remove:${account.platform}`, async () => {
    await removeLinkedAccount(state.userId, account.platform);
    replaceAccount(state, null, account.platform);
    state.setConfirmUnlink(null);
    return `${account.label} account unlinked.`;
  });
}
