// Server actions of the phased workflow view: save layout, edit as draft and publish.
import type { ReadJsonFn } from "../../../hooks/useAdminTabLoader.types";
import { positionsToSave } from "./phasedGraphLayout";
import { type Point } from "./phasedGraphTypes";
import {
  flowPublishPath,
  phasedDefinitionPath,
  phasedLayoutPath,
  publishProblem,
  type PhasedView,
} from "./phasedWorkflowModel";

export const message = (error: unknown, fallback: string) =>
  error instanceof Error ? error.message : fallback;

const post = (body: unknown): RequestInit => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

type Input = {
  flowId: string;
  readJson: ReadJsonFn;
  view: PhasedView | null;
  positions: Map<string, Point>;
  layoutPositions: Map<string, Point>;
  setBusy: (busy: boolean) => void;
  setProblem: (problem: string | null) => void;
  setNotice: (notice: string | null) => void;
  setView: (view: PhasedView) => void;
  load: () => Promise<void>;
};

export function phasedEditorActions({ flowId, readJson, view, positions, layoutPositions, setBusy, setProblem, setNotice,
  setView, load }: Input) {
  const saveLayout = async () => {
    if (!view) return;
    setBusy(true);
    setProblem(null);
    try {
      const next = await readJson<PhasedView>(phasedLayoutPath(flowId), post({
        base_version_id: view.version_id,
        positions: positionsToSave(positions, layoutPositions),
      }));
      setView(next);
      setNotice(next.version === view.version
        ? "The layout is unchanged."
        : `Layout saved in draft v${next.version}.${next.published_version ? ` Runs keep using published v${next.published_version} until you publish.` : ""}`);
    } catch (error) {
      setProblem(message(error, "The layout could not be saved."));
    } finally {
      setBusy(false);
    }
  };

  // A draft of the published version, opened in the designer.
  const editAsDraft = async () => {
    if (!view?.definition) return;
    setBusy(true);
    setProblem(null);
    try {
      // A workflow built from fragments is detached: the draft keeps its boxes as a plain workflow you can change.
      const next = await readJson<PhasedView>(phasedDefinitionPath(flowId), post({
        base_version_id: view.version_id, definition: view.definition, ...(view.composite ? { detach: true } : {}),
      }));
      setView(next);
      setNotice(`Draft v${next.version} made from v${view.version}${view.composite
        ? "; it no longer follows its building blocks" : ""}. Runs keep using v${view.version} until you publish.`);
    } catch (error) {
      setProblem(message(error, "The draft could not be made."));
    } finally {
      setBusy(false);
    }
  };

  const publish = async () => {
    if (!view) return;
    setBusy(true);
    setProblem(null);
    try {
      await readJson(flowPublishPath(view.version_id), post({}));
      setNotice(
        `Published version ${view.version}. New runs use it; running runs keep their version.`,
      );
      await load();
    } catch (error) {
      setProblem(publishProblem(error, "The version could not be published."));
    } finally {
      setBusy(false);
    }
  };

  return { saveLayout, editAsDraft, publish };
}
