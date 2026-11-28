import type { Dispatch, FormEvent, SetStateAction } from "react";
import type { AdminRuntime } from "../types/adminPanelTypes.runtimeCorp";

type ReadJsonFn = <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;

type AddRuntimeActionArgs = {
  readJson: ReadJsonFn;
  runtimeFormProvider: string;
  runtimeFormModel: string;
  runtimeFormPrimary: boolean;
  setRuntimeFormError: Dispatch<SetStateAction<string | null>>;
  setRuntimeFormLoading: Dispatch<SetStateAction<boolean>>;
  setRuntimes: Dispatch<SetStateAction<AdminRuntime[]>>;
  setShowAddRuntime: Dispatch<SetStateAction<boolean>>;
  setRuntimeFormModel: Dispatch<SetStateAction<string>>;
  setRuntimeFormPrimary: Dispatch<SetStateAction<boolean>>;
};

export function createHandleAddRuntime({
  readJson,
  runtimeFormProvider,
  runtimeFormModel,
  runtimeFormPrimary,
  setRuntimeFormError,
  setRuntimeFormLoading,
  setRuntimes,
  setShowAddRuntime,
  setRuntimeFormModel,
  setRuntimeFormPrimary,
}: AddRuntimeActionArgs) {
  return async (event: FormEvent, confirmModel: () => Promise<boolean>) => {
    event.preventDefault();
    setRuntimeFormError(null);
    setRuntimeFormLoading(true);
    try {
      // The choices were read when the form showed the provider; a Providers
      // change that landed later (a bulk toggle still running during the tab
      // switch, another admin) must not create a runtime for an inactive model.
      if (!(await confirmModel())) {
        setRuntimeFormError(
          "The selected model is no longer active for this provider. Choose an active model.",
        );
        return;
      }
      await readJson<AdminRuntime>("/admin/chat/api/panel/runtimes", {
        method: "POST",
        body: JSON.stringify({
          provider_id: runtimeFormProvider,
          model_id: runtimeFormModel,
          make_primary: runtimeFormPrimary,
        }),
      });
      const updated = await readJson<AdminRuntime[]>(
        "/admin/chat/api/panel/runtimes",
      );
      setRuntimes(updated);
      setShowAddRuntime(false);
      setRuntimeFormModel("");
      setRuntimeFormPrimary(false);
    } catch (err) {
      setRuntimeFormError(err instanceof Error ? err.message : "Failed");
    } finally {
      setRuntimeFormLoading(false);
    }
  };
}

type RuntimeTargetsActionArgs = {
  readJson: ReadJsonFn;
  setRuntimes: Dispatch<SetStateAction<AdminRuntime[]>>;
};

export function createHandleMoveRuntime({
  readJson,
  setRuntimes,
}: RuntimeTargetsActionArgs) {
  return async (targetId: string, direction: "up" | "down") => {
    try {
      const updated = await readJson<AdminRuntime[]>(
        `/admin/chat/api/panel/runtimes/${targetId}/move`,
        {
          method: "POST",
          body: JSON.stringify({ direction }),
        },
      );
      setRuntimes(updated);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed");
    }
  };
}

export function createHandleToggleRuntime({
  readJson,
  setRuntimes,
}: RuntimeTargetsActionArgs) {
  return async (targetId: string) => {
    try {
      const updated = await readJson<AdminRuntime>(
        `/admin/chat/api/panel/runtimes/${targetId}/toggle`,
        {
          method: "POST",
        },
      );
      setRuntimes((prev) =>
        prev.map((item) =>
          item.id === targetId
            ? { ...item, is_active: updated.is_active }
            : item,
        ),
      );
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed");
    }
  };
}

export function createHandleDeleteRuntime({
  readJson,
  setRuntimes,
}: RuntimeTargetsActionArgs) {
  return async (targetId: string, label: string) => {
    if (!confirm(`Remove "${label}" from runtime priority list?`)) return;
    try {
      await readJson(`/admin/chat/api/panel/runtimes/${targetId}`, {
        method: "DELETE",
      });
      const updated = await readJson<AdminRuntime[]>(
        "/admin/chat/api/panel/runtimes",
      );
      setRuntimes(updated);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed");
    }
  };
}

type RuntimeTagsActionArgs = {
  readJson: ReadJsonFn;
  runtimeTagsInput: string;
  setRuntimes: Dispatch<SetStateAction<AdminRuntime[]>>;
  setEditingRuntimeTags: Dispatch<SetStateAction<string | null>>;
};

export function createHandleSaveRuntimeTags({
  readJson,
  runtimeTagsInput,
  setRuntimes,
  setEditingRuntimeTags,
}: RuntimeTagsActionArgs) {
  return async (runtimeId: string) => {
    const tags = runtimeTagsInput
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    const updated = await readJson<AdminRuntime>(
      `/admin/chat/api/panel/runtimes/${runtimeId}`,
      {
        method: "PUT",
        body: JSON.stringify({ use_case_tags: tags }),
      },
    );
    setRuntimes((prev) =>
      prev.map((item) => (item.id === updated.id ? updated : item)),
    );
    setEditingRuntimeTags(null);
  };
}
