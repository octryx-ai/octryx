import { createSessionActionHandlers } from "./useSessionActions.handlers";
import type { UseSessionActionsArgs } from "./useSessionActions.types";

export function useSessionActions(args: UseSessionActionsArgs) {
  return createSessionActionHandlers(args);
}
