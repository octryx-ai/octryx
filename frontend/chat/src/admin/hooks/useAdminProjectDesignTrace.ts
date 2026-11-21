import { createProjectDesignTraceArtifactActions } from "./useAdminProjectDesignTraceArtifactActions";
import { createProjectDesignTraceCustomWorkflowActions } from "./useAdminProjectDesignTraceCustomWorkflowActions";
import { createProjectDesignTraceWorkflowActions } from "./useAdminProjectDesignTraceWorkflowActions";
import type { UseAdminProjectDesignTraceArgs } from "./useAdminProjectDesignTrace.types";

export function useAdminProjectDesignTrace(
  args: UseAdminProjectDesignTraceArgs,
) {
  return {
    ...createProjectDesignTraceArtifactActions(args),
    ...createProjectDesignTraceCustomWorkflowActions(args),
    ...createProjectDesignTraceWorkflowActions(args),
  };
}
