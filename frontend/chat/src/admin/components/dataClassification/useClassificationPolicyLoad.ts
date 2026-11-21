// Loading of the classification policy page: the published policy, and for editors the versions, the default level,
// the policy engine mode and (on demand) the Workspaces with their level.
import { useCallback, useEffect, type Dispatch, type SetStateAction } from "react";

import { readJson } from "../../utils/adminPanelHelpers";
import type { ClassifiedWorkspace } from "./ClassificationWorkspacesTab";
import { readVersions, type VersionsView } from "./classificationVersionsModel";
import { policyLoadErrorText, readClassificationPolicy } from "./classificationPolicyModel";
import type { ClassificationPolicy } from "./classificationPolicyModel";
import {
  loadClassificationPolicy,
  loadClassificationVersions,
  loadClassificationWorkspaces,
  loadInstanceDefault,
} from "./dataClassificationApi";
import { readInstanceDefault } from "./dataClassificationModel";
import type { InstanceDefault } from "./dataClassificationTypes";

const readWorkspaces = (answer: unknown): ClassifiedWorkspace[] => {
  const rows = answer && typeof answer === "object" ? (answer as { workspaces?: unknown }).workspaces : null;
  return Array.isArray(rows) ? rows.filter((row) => row && typeof row === "object") as ClassifiedWorkspace[] : [];
};

type Setter<T> = Dispatch<SetStateAction<T>>;

type ClassificationPolicyLoadArgs = {
  isAdmin: boolean;
  tab: string;
  ruleDrawer: string | null;
  workspaces: ClassifiedWorkspace[] | null;
  setPolicy: Setter<ClassificationPolicy | null>;
  setProblem: Setter<string | null>;
  setVersions: Setter<VersionsView | null>;
  setInstanceDefault: Setter<InstanceDefault | null>;
  setEngineMode: Setter<string | null>;
  setWorkspaces: Setter<ClassifiedWorkspace[] | null>;
};

export function useClassificationPolicyLoad({
  isAdmin, tab, ruleDrawer, workspaces, setPolicy, setProblem, setVersions, setInstanceDefault, setEngineMode, setWorkspaces,
}: ClassificationPolicyLoadArgs) {
  const load = useCallback(async () => {
    let read: ClassificationPolicy | null = null;
    try {
      read = readClassificationPolicy(await loadClassificationPolicy(), isAdmin);
      setPolicy(read);
      setProblem(read ? null : "The server's answer listed no classification levels.");
    } catch (error) {
      setPolicy(null);
      setProblem(policyLoadErrorText(error));
      return;
    }
    if (!read?.canEdit) return;
    const [versionsAnswer, defaultAnswer, status] = await Promise.allSettled([
      loadClassificationVersions(), loadInstanceDefault(), readJson<{ mode?: unknown }>("/api/v1/admin/policy-engine/status"),
    ]);
    setVersions(versionsAnswer.status === "fulfilled" ? readVersions(versionsAnswer.value) : null);
    setInstanceDefault(defaultAnswer.status === "fulfilled" ? readInstanceDefault(defaultAnswer.value) : null);
    setEngineMode(status.status === "fulfilled" && typeof status.value?.mode === "string" ? status.value.mode : null);
  }, [isAdmin, setEngineMode, setInstanceDefault, setPolicy, setProblem, setVersions]);

  const loadWorkspaces = useCallback(async () => {
    try {
      setWorkspaces(readWorkspaces(await loadClassificationWorkspaces()));
    } catch {
      setWorkspaces([]);
    }
  }, [setWorkspaces]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if ((tab === "workspaces" || ruleDrawer === "add") && workspaces === null) void loadWorkspaces();
  }, [tab, ruleDrawer, workspaces, loadWorkspaces]);

  return { load, loadWorkspaces };
}
