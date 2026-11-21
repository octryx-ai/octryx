import { useCallback, useEffect, useState } from "react";

import { useAdminNavigation } from "../../adminNavigation";
import { readJson } from "../../utils/adminPanelHelpers";
import "../settingsKit/settingsKit.css";
import type { Contract, WorkspaceModels } from "./workspaceModelsModel";
import { contractProblems, modelsSaveBody, readWorkspaceModels, saveErrorText } from "./workspaceModelsModel";
import { ModelsDefaultsCard, ModelsSeatsCard, ModelsWhichCard, type Level } from "./WorkspaceModelsParts";

const readLevels = (payload: unknown): Level[] => {
  const levels = payload && typeof payload === "object" ? (payload as { levels?: unknown }).levels : null;
  return Array.isArray(levels) ? levels.map((item) => ({
    key: String(item?.level ?? ""), label: String(item?.label ?? item?.level ?? ""), color: typeof item?.color === "string" ? item.color : null,
  })) : [];
};

// The Workspace's models (view and draft), the data levels and the load/save state.
function useWorkspaceModels(path: string) {
  const [view, setView] = useState<WorkspaceModels | null>(null);
  const [draft, setDraft] = useState<Contract | null>(null);
  const [levels, setLevels] = useState<Level[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const apply = (answer: unknown) => {
    const read = readWorkspaceModels(answer);
    setView(read);
    setDraft(read?.contract ?? null);
  };
  const load = useCallback(async () => {
    try {
      apply(await readJson<unknown>(path));
    } catch (error) {
      setProblem((error as { status?: number }).status === 403 ? "Only the Workspace's admins can change its models." : "The models could not be loaded.");
    }
    readJson<unknown>("/api/v1/admin/data-classification/policy").then((answer) => setLevels(readLevels(answer))).catch(() => setLevels([]));
  }, [path]);
  useEffect(() => { void load(); }, [load]);

  return { view, draft, setDraft, levels, problem, message, setMessage, busy, setBusy, apply };
}

// Workspace → Models: which models this
// Workspace may use — every model cleared for its level, or a selection — as one list by display name with where each
// can be used, the default model, and the Claude Code seat card with company models in /model. Clearance, approval and
// temperature are set per model in Runtime.
export function WorkspaceModelsSection({ projectId }: { projectId: string }) {
  const { openAdminTab } = useAdminNavigation();
  const path = `/api/v1/admin/workspaces/${encodeURIComponent(projectId)}/models`;
  const { view, draft, setDraft, levels, problem, message, setMessage, busy, setBusy, apply } = useWorkspaceModels(path);

  if (problem) return <p className="sk-err" role="alert">{problem}</p>;
  if (!view || !draft) return <p className="sk-hint" role="status">Loading the models…</p>;

  const level = levels.find((item) => item.key === view.level);
  const levelLabel = level?.label ?? view.level ?? "this level";
  const problems = contractProblems(draft, view.models);
  const changed = JSON.stringify(modelsSaveBody(draft)) !== JSON.stringify(modelsSaveBody(view.contract));
  const save = async () => {
    setBusy(true);
    setMessage(null);
    try {
      apply(await readJson<unknown>(path, { method: "PUT", body: JSON.stringify(modelsSaveBody(draft)) }));
      setMessage({ ok: true, text: "Models saved." });
    } catch (error) {
      setMessage({ ok: false, text: saveErrorText(error) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sk-page" data-testid="workspace-models">
      <ModelsWhichCard view={view} draft={draft} setDraft={setDraft} busy={busy} openAdminTab={openAdminTab} levels={levels}
        levelLabel={levelLabel} projectId={projectId} />
      <ModelsDefaultsCard view={view} draft={draft} setDraft={setDraft} busy={busy} openAdminTab={openAdminTab} />
      <ModelsSeatsCard view={view} draft={draft} projectId={projectId} levelLabel={levelLabel} />
      {problems.length ? <ul className="sk-err" role="alert">{problems.map((line) => <li key={line}>{line}</li>)}</ul> : null}
      {message ? <p className={message.ok ? "admin-panel__success" : "sk-err"} role={message.ok ? "status" : "alert"}>{message.text}</p> : null}
      <div className="sk-row sk-row--end">
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="workspace-models-save"
          disabled={busy || !changed || problems.length > 0} onClick={() => void save()}>
          {busy ? "Saving…" : "Save models"}
        </button>
      </div>
    </div>
  );
}
