// Identity group actions of the users tab: create, update, toggle and confirmed delete.
import type { Dispatch, FormEvent, SetStateAction } from "react";

import type { ConfirmRequest } from "../confirm/useConfirmAction";
import type { AdminIdentityGroupRow, AdminReadJsonFn } from "./identityTypes";

export type AdminGroupActionsDeps = {
  readJson: AdminReadJsonFn;
  ask: (request: ConfirmRequest) => void;
  groupName: string;
  groupDescription: string;
  setGroups: Dispatch<SetStateAction<AdminIdentityGroupRow[]>>;
  setGroupName: Dispatch<SetStateAction<string>>;
  setGroupDescription: Dispatch<SetStateAction<string>>;
  setGroupLoading: Dispatch<SetStateAction<string | null>>;
  setGroupError: Dispatch<SetStateAction<string | null>>;
  setShowCreateGroup: Dispatch<SetStateAction<boolean>>;
};

export function createAdminGroupActions(deps: AdminGroupActionsDeps) {
  const { readJson, ask, setGroups, setGroupError } = deps;
  const handleDeleteGroup = (group: AdminIdentityGroupRow) => ask({
    title: `Delete group ${group.name}?`, confirmLabel: `Delete ${group.name}`, done: `Group ${group.name} deleted.`,
    run: async () => {
      await readJson(`/admin/chat/api/panel/identity-groups/${group.id}`, { method: "DELETE" });
      setGroups((current) => current.filter((item) => item.id !== group.id));
      setGroupError(null);
    },
  });

  return {
    handleCreateGroup: groupCreator(deps),
    handleUpdateGroup: groupUpdater(deps),
    handleToggleGroup: groupToggler(deps),
    handleDeleteGroup,
  };
}

function groupCreator({
  readJson, groupName, groupDescription, setGroups, setGroupName, setGroupDescription, setGroupLoading, setGroupError, setShowCreateGroup,
}: AdminGroupActionsDeps) {
  return async (event: FormEvent) => {
    event.preventDefault();
    setGroupLoading("create");
    try {
      const created = await readJson<AdminIdentityGroupRow>(
        "/admin/chat/api/panel/identity-groups",
        {
          method: "POST",
          body: JSON.stringify({
            name: groupName,
            description: groupDescription,
          }),
        },
      );
      setGroups((current) =>
        [...current, created].sort((a, b) => a.name.localeCompare(b.name)),
      );
      setGroupName("");
      setGroupDescription("");
      setGroupError(null);
      setShowCreateGroup(false);
    } catch (error) {
      setGroupError(
        error instanceof Error ? error.message : "Failed to create group",
      );
    } finally {
      setGroupLoading(null);
    }
  };
}

function groupUpdater({ readJson, setGroups, setGroupLoading, setGroupError }: AdminGroupActionsDeps) {
  return async (
    group: AdminIdentityGroupRow,
    payload: {
      description?: string;
      rls_attributes?: Array<{ key: string; value: string }>;
    },
  ) => {
    setGroupLoading(
      payload.rls_attributes ? `rls:${group.id}` : `update:${group.id}`,
    );
    try {
      const updated = await readJson<AdminIdentityGroupRow>(
        `/admin/chat/api/panel/identity-groups/${group.id}`,
        {
          method: "PUT",
          body: JSON.stringify(payload),
        },
      );
      setGroups((current) =>
        current.map((item) => (item.id === group.id ? updated : item)),
      );
      setGroupError(null);
    } catch (error) {
      setGroupError(
        error instanceof Error ? error.message : "Failed to update group",
      );
    } finally {
      setGroupLoading(null);
    }
  };
}

function groupToggler({ readJson, setGroups, setGroupLoading, setGroupError }: AdminGroupActionsDeps) {
  return async (group: AdminIdentityGroupRow) => {
    setGroupLoading(`toggle:${group.id}`);
    try {
      const updated = await readJson<AdminIdentityGroupRow>(
        `/admin/chat/api/panel/identity-groups/${group.id}`,
        {
          method: "PUT",
          body: JSON.stringify({ is_active: !group.is_active }),
        },
      );
      setGroups((current) =>
        current.map((item) => (item.id === group.id ? updated : item)),
      );
      setGroupError(null);
    } catch (error) {
      setGroupError(
        error instanceof Error ? error.message : "Failed to update group",
      );
    } finally {
      setGroupLoading(null);
    }
  };
}
