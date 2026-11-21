// The phase steps editor's state and its server actions: save the draft and apply a preview of the edited steps.
import { useEffect, useRef, useState } from "react";

import type { ReadJsonFn } from "../../../hooks/useAdminTabLoader.types";
import { readStepsGraph, readStepsGraphView, readValidationReport, type StepsGraphNode, type StepsGraphView, type ValidationReport } from "./stepsGraphModel";

export const post = (body: unknown): RequestInit => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});
export const message = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback);

export function useStepsWorkflowState(onDirtyChange?: (dirty: boolean) => void) {
  const [view, setView] = useState<StepsGraphView | null>(null);
  const [nodes, setNodes] = useState<StepsGraphNode[]>([]);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [dirty, setDirty] = useState(false);
  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);
  const [busy, setBusy] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // A new step or check in the side panel, not yet part of the draft.
  const [adding, setAdding] = useState<StepsGraphNode | null>(null);
  const [toolNames, setToolNames] = useState<string[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const previewRequest = useRef(0);
  return {
    view, setView, nodes, setNodes, report, setReport, dirty, setDirty, busy, setBusy, selectedId, setSelectedId, adding, setAdding, toolNames, setToolNames, problem, setProblem, notice, setNotice, previewRequest,
  };
}

export type StepsWorkflowState = ReturnType<typeof useStepsWorkflowState>;

type ActionContext = {
  state: StepsWorkflowState;
  readJson: ReadJsonFn;
  graphPath: string;
};

// The server's preview of the edited steps: re-derived modes, approvals and allowed tools and the validation.
export async function applyStepsPreview(state: StepsWorkflowState, readJson: ReadJsonFn, graphPath: string, request: number) {
  const { nodes, setNodes, setReport, setProblem, previewRequest } = state;
  try {
    const body = await readJson<{ graph: unknown; validation_report: unknown }>(
      `${graphPath}/preview`, post({ graph: { nodes } }));
    if (request !== previewRequest.current) return;
    const derived = readStepsGraph(body.graph).nodes;
    // Keep the editor's own ids for the stored nodes so the selection survives the re-derivation.
    const stored = nodes.filter((node) => node.kind === "step" || node.kind === "check");
    let index = 0;
    setNodes(derived.map((node) => (node.kind === "step" || node.kind === "check" ? { ...node, id: stored[index++]?.id ?? node.id } : node)));
    setReport(readValidationReport(body.validation_report));
  } catch (error) {
    if (request === previewRequest.current) setProblem(message(error, "The edit could not be checked."));
  }
}

export async function saveStepsDraft({ state, readJson, graphPath }: ActionContext) {
  const { view, nodes, setBusy, setProblem, setView, setNodes, setReport, setDirty, setSelectedId, setNotice } = state;
  if (!view) return;
  setBusy(true);
  setProblem(null);
  try {
    const saved = readStepsGraphView(await readJson<unknown>(graphPath,
      post({ base_version_id: view.versionId, graph: { nodes } })));
    setView(saved);
    setNodes(saved.graph.nodes);
    setReport(saved.report);
    setDirty(false);
    setSelectedId(null);
    setNotice(`Saved as draft version ${saved.version} of the workflow. Publish the workflow to run it.`);
  } catch (error) {
    setProblem(message(error, "The draft could not be saved."));
  } finally {
    setBusy(false);
  }
}
