import { createContext, useCallback, useContext } from "react";

import { NO_POLICY_NAMES, policyIdLabel } from "./policyIdLabels";
import type { PolicyNames } from "./policyIdLabels";

// The names the Policies page knows (Workspaces, custom policies), provided once by the page so every place that
// lists determining policies (builder check step, impact examples, test bench, decisions, test reports) labels them
// the same way. Outside the page the labels fall back to readable forms of the id itself.
export const PolicyNamesContext = createContext<PolicyNames>(NO_POLICY_NAMES);

export function usePolicyNames(): PolicyNames {
  return useContext(PolicyNamesContext);
}

export function usePolicyLabel(): (id: string) => string {
  const names = usePolicyNames();
  return useCallback((id: string) => policyIdLabel(id, names), [names]);
}
