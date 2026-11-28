import { createContext, useCallback, useContext } from "react";

import { NO_POLICY_NAMES, policyIdLabel } from "./policyIdLabels";
import type { PolicyNames } from "./policyIdLabels";

export const PolicyNamesContext = createContext<PolicyNames>(NO_POLICY_NAMES);

export function usePolicyNames(): PolicyNames {
  return useContext(PolicyNamesContext);
}

export function usePolicyLabel(): (id: string) => string {
  const names = usePolicyNames();
  return useCallback((id: string) => policyIdLabel(id, names), [names]);
}
