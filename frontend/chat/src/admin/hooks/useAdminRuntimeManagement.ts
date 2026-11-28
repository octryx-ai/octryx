import { createHandleSaveRuntimeSettings } from "./useAdminRuntimeManagementActions";
import {
  createHandleAddRuntime,
  createHandleDeleteRuntime,
  createHandleMoveRuntime,
  createHandleSaveRuntimeTags,
  createHandleToggleRuntime,
} from "./useAdminRuntimeTargetActions";
import type { UseAdminRuntimeManagementArgs } from "./useAdminRuntimeManagement.types";

export function useAdminRuntimeManagement(args: UseAdminRuntimeManagementArgs) {
  const { readJson, setRuntimes } = args;
  const handleAddRuntime = createHandleAddRuntime({
    readJson,
    runtimeFormProvider: args.runtimeFormProvider,
    runtimeFormModel: args.runtimeFormModel,
    runtimeFormPrimary: args.runtimeFormPrimary,
    setRuntimeFormError: args.setRuntimeFormError,
    setRuntimeFormLoading: args.setRuntimeFormLoading,
    setRuntimes,
    setShowAddRuntime: args.setShowAddRuntime,
    setRuntimeFormModel: args.setRuntimeFormModel,
    setRuntimeFormPrimary: args.setRuntimeFormPrimary,
  });

  // The settings save reads every runtime settings draft and setter from the management args.
  const handleSaveRuntimeSettings = createHandleSaveRuntimeSettings(args);
  const handleMoveRuntime = createHandleMoveRuntime({ readJson, setRuntimes });
  const handleToggleRuntime = createHandleToggleRuntime({ readJson, setRuntimes });
  const handleDeleteRuntime = createHandleDeleteRuntime({ readJson, setRuntimes });

  const handleSaveRuntimeTags = createHandleSaveRuntimeTags({
    readJson,
    runtimeTagsInput: args.runtimeTagsInput,
    setRuntimes,
    setEditingRuntimeTags: args.setEditingRuntimeTags,
  });

  return {
    handleAddRuntime,
    handleDeleteRuntime,
    handleMoveRuntime,
    handleSaveRuntimeSettings,
    handleSaveRuntimeTags,
    handleToggleRuntime,
  };
}
