// Designer saving and publishing: save a draft version, publish, or request publishing from a second admin.
import type { ReadJsonFn } from "../../../../hooks/useAdminTabLoader.types";
import { flowPublishPath, flowReviewPath, phasedDefinitionPath, publishProblem, type PhasedView } from "../phasedWorkflowModel";
import { message, post } from "./designerEditorHelpers";
import { toDefinition } from "./modelDefinition";
import { type DesignModel } from "./modelCore";

export function createDesignerPublishing({
  readJson, view, model, named, onView, onReload, setBusy, setProblem, setNotice,
}: {
  readJson: ReadJsonFn; view: PhasedView; model: DesignModel; named: string;
  onView: (view: PhasedView) => void; onReload: () => Promise<void>;
  setBusy: (busy: boolean) => void; setProblem: (problem: string | null) => void; setNotice: (notice: string | null) => void;
}) {
  const save = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const next = await readJson<PhasedView>(phasedDefinitionPath(view.flow_id), post({
        base_version_id: view.version_id, definition: toDefinition(model), ...(named && named !== view.title ? { title: named } : {}),
      }));
      onView(next);
      const errors = next.validation_report.errors.length;
      setNotice(`Saved as draft v${next.version}.${errors ? " Fix the problems listed above before publishing." : " It can be published."}`);
    } catch (error) {
      setProblem(message(error, "The draft could not be saved."));
    } finally {
      setBusy(false);
    }
  };
  const publish = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await readJson(flowPublishPath(view.version_id), post({}));
      setNotice(`Published version ${view.version}. New runs use it; running runs keep their version.`);
      await onReload();
    } catch (error) {
      setProblem(publishProblem(error, "The version could not be published."));
    } finally {
      setBusy(false);
    }
  };
  // Four eyes (D2b2): the author asks; a second admin publishes.
  const requestPublishing = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await readJson(flowReviewPath(view.version_id), post({}));
      setNotice("Publishing requested. Another admin checks this version and publishes it.");
      await onReload();
    } catch (error) {
      setProblem(message(error, "Publishing could not be requested."));
    } finally {
      setBusy(false);
    }
  };
  return { save, publish, requestPublishing };
}
