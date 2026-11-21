import { useEffect, useRef, useState } from "react";

import { loadContentDetectors } from "./builderContentApi";
import { EMPTY_DETECTORS, contentAction, effectBadge, readDetectorCatalog, routeTargetWarning } from "./builderContentModel";
import type { DetectorCatalog } from "./builderContentModel";
import { renderPolicyModel } from "./policyEngineApi";
import { refusalText } from "./policyEngineVersions";
import { missingPlaceholders, startStep, visibleSteps } from "./policyBuilderModel";
import type { BuilderModel, StepId } from "./policyBuilderModel";
import { readSegments } from "./policyCatalogModel";
import type { Catalog, PolicyView, Segment } from "./policyCatalogModel";

export type Preview = { valid: boolean; issues: { path: string; code: string; message: string }[]; text: string; sentence: Segment[]; scope: string; warnings: { code: string; message: string }[] };
const EMPTY_PREVIEW: Preview = { valid: false, issues: [], text: "", sentence: [], scope: "", warnings: [] };

export type BuilderSession = { model: BuilderModel; isNew: boolean; title: string; originalId: string | null };

function readPreview(raw: unknown): Preview {
  const value = (typeof raw === "object" && raw !== null ? raw : {}) as Record<string, unknown>;
  const list = (key: string) => (Array.isArray(value[key]) ? (value[key] as Record<string, unknown>[]) : []);
  return {
    valid: value.valid === true,
    issues: list("issues").map((item) => ({ path: String(item.path ?? ""), code: String(item.code ?? ""), message: String(item.message ?? "") })),
    text: typeof value.text === "string" ? value.text : "",
    sentence: readSegments(value.sentence),
    scope: typeof value.scope === "string" ? value.scope : "",
    warnings: list("warnings").map((item) => ({ code: String(item.code ?? ""), message: String(item.message ?? "") })),
  };
}

// The builder's state: the model, the step, the server preview (debounced, latest request wins) and the content
// detector catalog (loaded once the policy checks content).
export function usePolicyBuilder(session: BuilderSession, catalog: Catalog, previewDelay: number) {
  const [model, setModel] = useState<BuilderModel>(session.model);
  const [step, setStep] = useState<StepId>(() => (session.isNew && !session.model.template ? "basics" : startStep(session.model, catalog)));
  const [idLocked, setIdLocked] = useState(!session.isNew);
  const [preview, setPreview] = useState<Preview>(EMPTY_PREVIEW);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [confirmCedar, setConfirmCedar] = useState(false);
  const [detectors, setDetectors] = useState<DetectorCatalog | null>(null);
  const request = useRef(0);
  const content = contentAction(model);

  useEffect(() => {
    if (!content || detectors) return;
    let live = true;
    void loadContentDetectors().then((raw) => { if (live) setDetectors(readDetectorCatalog(raw)); })
      .catch((error) => { if (live) { setDetectors(EMPTY_DETECTORS); setProblem(refusalText(error)); } });
    return () => { live = false; };
  }, [content, detectors]);

  useEffect(() => {
    const ticket = ++request.current;
    if (!model.actions.length || !model.id) {
      setPreview(EMPTY_PREVIEW);
      return;
    }
    const timer = setTimeout(() => {
      void renderPolicyModel(model).then((raw) => { if (ticket === request.current) setPreview(readPreview(raw)); })
        .catch((error) => { if (ticket === request.current) setPreview({ ...EMPTY_PREVIEW, issues: [{ path: "", code: "", message: refusalText(error) }] }); });
    }, previewDelay);
    return () => clearTimeout(timer);
  }, [model, previewDelay]);

  return { model, setModel, step, setStep, idLocked, setIdLocked, preview, busy, setBusy, problem, setProblem, confirmCedar, setConfirmCedar, detectors, content };
}

// What the builder shows around the step: the steps, the required inputs, the warnings and why saving is blocked.
export function builderStatus(model: BuilderModel, step: StepId, preview: Preview, catalog: Catalog, view: PolicyView) {
  const missing = missingPlaceholders(model, catalog);
  // A missing template input is shown once, as "Required" with its hint, not again as a server issue.
  const issues = preview.issues.filter((issue) => issue.code !== "builder_template_placeholder_missing");
  const required = missing.map((item) => item.field);
  const target = view.editTarget;
  const steps = visibleSteps(model);
  const current: StepId = steps.some((item) => item.id === step) ? step : "what";
  const index = steps.findIndex((item) => item.id === current);
  const badge = effectBadge(model);
  const routeWarning = routeTargetWarning(model, steps.findIndex((item) => item.id === "outcome") + 1,
    missing.length === 1 && missing[0].field === "outcome.reroute_to");
  // The route target is asked for once, by the route warning, not again as a "Required" line.
  const requiredShown = routeWarning ? missing.filter((item) => item.field !== "outcome.reroute_to") : missing;
  const blocked = !target ? "The draft is in review and frozen." : !model.actions.length ? "Pick at least one action."
    : !model.id ? "Give the policy a name." : missing.length ? `Fill in: ${missing.map((item) => item.label).join(", ")}.`
      : !preview.valid ? "Fix the problems below." : null;
  const draftLabel = !target ? "Draft in review (frozen)" : target.createsDraft ? "Creates a new draft" : `Saves into draft v${target.version}`;
  return { issues, required, target, steps, current, index, badge, routeWarning, requiredShown, blocked, draftLabel };
}
