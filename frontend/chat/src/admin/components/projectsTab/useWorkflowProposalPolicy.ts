// State of the Workspace workflow proposal policy: load the project config, keep the draft choices and write patches.
import { useEffect, useState } from "react";

import { governedRequest, type GovernedIssue } from "../governedWrite/governedRequest";
import { workflowProposalPolicyState, type WorkflowProposalPolicyState } from "./workflowProposalPolicy";

type ProjectConfigPayload = { config?: Record<string, unknown> };

export function useWorkflowProposalPolicy(projectId: string) {
  const configUrl = `/admin/chat/api/panel/projects/${encodeURIComponent(projectId)}/config`;
  const [stored, setStored] = useState<WorkflowProposalPolicyState | null>(null);
  const [choice, setChoice] = useState<WorkflowProposalPolicyState>("default");
  const [config, setConfig] = useState<Record<string, unknown> | undefined>(undefined);
  const [issues, setIssues] = useState<GovernedIssue[]>([]);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    setStored(null);
    setIssues([]);
    setNotice(null);
    void governedRequest<ProjectConfigPayload>(configUrl, { method: "GET" }).then((outcome) => {
      if (cancelled) return;
      if (!outcome.ok) {
        setIssues(outcome.issues);
        return;
      }
      applyConfig(outcome.data.config);
    });
    return () => {
      cancelled = true;
    };
  }, [projectId, configUrl]);

  function applyConfig(next: Record<string, unknown> | undefined) {
    const state = workflowProposalPolicyState(next);
    setConfig(next);
    setStored(state);
    setChoice(state);
  }

  const write = async (body: Record<string, unknown>, done: string) => {
    setSaving(true);
    setIssues([]);
    setNotice(null);
    const outcome = await governedRequest<ProjectConfigPayload>(configUrl, { method: "PUT", body });
    setSaving(false);
    if (!outcome.ok) {
      setIssues(outcome.issues);
      return;
    }
    applyConfig(outcome.data.config);
    setNotice(done);
  };

  return { stored, choice, setChoice, config, issues, saving, notice, write };
}
