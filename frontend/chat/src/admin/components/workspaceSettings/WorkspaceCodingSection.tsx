import { useCallback, useEffect, useState } from "react";

import { AgentsHandoffPolicy } from "../../../chat/agents/AgentsHandoffPolicy";
import "../../../chat/agents/agents.css";
import { DeviceRunsPolicyCard } from "../../../chat/devices/DeviceRunsPolicyCard";
import { RunPhaseSettingsCard } from "../../../chat/devices/RunPhaseSettingsCard";
import { ToolDefaultsCard } from "../../../chat/devices/ToolDefaultsCard";
import { useAdminNavigation } from "../../adminNavigation";
import { readJson } from "../../utils/adminPanelHelpers";
import "../settingsKit/settingsKit.css";
import { AgentSandboxDomainsPanel } from "../workspaceKnowledge/AgentSandboxDomainsPanel";
import { WorkspaceEngineCard } from "../../../chat/engines/EngineCards";
import { CodingRuleDrawer } from "./CodingRuleDrawer";
import { CodingModelCallsCard, CodingRoleModesCard, CodingRulesCard } from "./WorkspaceCodingParts";
import { WorkspaceTranscriptsCard } from "./WorkspaceTranscriptsCard";
import type { Coding } from "./workspaceSettingsModel";
import { codingPayload, readCoding, settingsErrorText } from "./workspaceSettingsModel";

// The Workspace's coding-tool policy (saved and draft), the load/save state and the save of a draft.
function useWorkspaceCoding(path: string) {
  const [saved, setSaved] = useState<Coding | null>(null);
  const [draft, setDraft] = useState<Coding | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);

  const apply = (answer: unknown) => {
    const read = readCoding(answer);
    setSaved(read);
    setDraft(read);
    if (!read) setProblem("The server's answer was not a coding-tools policy.");
  };
  const load = useCallback(async () => {
    try {
      apply(await readJson<unknown>(path));
    } catch (error) {
      setProblem((error as { status?: number }).status === 403 ? "Only the Workspace's admins can see these rules." : "The coding-tool rules could not be loaded.");
    }
  }, [path]);
  useEffect(() => { void load(); }, [load]);

  const saveDraft = async (draft: Coding) => {
    setBusy(true);
    setMessage(null);
    try {
      apply(await readJson<unknown>(path, { method: "PUT", body: JSON.stringify(codingPayload(draft)) }));
      setMessage({ ok: true, text: "Saved. The rules apply to the next tool call." });
    } catch (error) {
      setMessage({ ok: false, text: settingsErrorText(error) });
    } finally {
      setBusy(false);
    }
  };

  return { saved, draft, setDraft, problem, message, adding, setAdding, busy, saveDraft };
}

// Workspace → Coding tools & devices:
// governed routing, device runs, handoff, the command & file rules (agent_gateway_policy.tool_rules and
// client_permissions.deny — each also published as a generated policy), the sandbox domains, handoff and the full
// session transcripts switch and the coding engine (Claude Code or Codex). The engine and transcript cards answer for
// members too (read-only), so they stay when the admin-only rules cannot be loaded.
export function WorkspaceCodingSection({ projectId, isPlatformAdmin, onOpenModels }: {
  projectId: string;
  isPlatformAdmin: boolean;
  onOpenModels: () => void;
}) {
  const { openAdminTab } = useAdminNavigation();
  const path = `/api/v1/admin/workspaces/${encodeURIComponent(projectId)}/coding`;
  const { saved, draft, setDraft, problem, message, adding, setAdding, busy, saveDraft } = useWorkspaceCoding(path);

  if (problem) {
    return (
      <div className="sk-wsec" data-testid="workspace-coding">
        <WorkspaceEngineCard projectId={projectId} />
        <p className="sk-err" role="alert">{problem}</p>
        <WorkspaceTranscriptsCard projectId={projectId} />
      </div>
    );
  }
  if (!draft || !saved) return <p className="sk-hint" role="status">Loading the coding-tool rules…</p>;

  const changed = JSON.stringify(draft) !== JSON.stringify(saved);
  const save = () => saveDraft(draft);

  const draftProps = { draft, saved, setDraft, changed, busy, save };

  return (
    <div className="sk-wsec" data-testid="workspace-coding">
      <WorkspaceEngineCard projectId={projectId} />

      <CodingModelCallsCard draft={draft} setDraft={setDraft} onOpenModels={onOpenModels} />

      <DeviceRunsPolicyCard projectId={projectId} isPlatformAdmin={isPlatformAdmin} />

      <RunPhaseSettingsCard projectId={projectId} />

      <ToolDefaultsCard projectId={projectId} />

      <CodingRoleModesCard {...draftProps} isPlatformAdmin={isPlatformAdmin} />

      <CodingRulesCard {...draftProps} message={message} onAdd={() => setAdding(true)} openAdminTab={openAdminTab} />

      <section className="admin-panel__card">
        <AgentSandboxDomainsPanel workspaceId={projectId} />
      </section>

      <AgentsHandoffPolicy projectId={projectId} />

      <WorkspaceTranscriptsCard projectId={projectId} />

      {adding ? (
        <CodingRuleDrawer taken={draft.toolRules.map((rule) => rule.id)} onClose={() => setAdding(false)}
          onAdd={(rule) => { setDraft({ ...draft, toolRules: [...draft.toolRules, rule] }); setAdding(false); }} />
      ) : null}
    </div>
  );
}
