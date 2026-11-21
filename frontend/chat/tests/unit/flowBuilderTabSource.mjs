// The Flow Builder tab's source: the entry component joined with the modules it was split into.
import { readFileSync } from "node:fs";

const FILES = [
  "AdminFlowBuilderTab.tsx",
  "FlowBuilderEditorParts.tsx",
  "flowBuilderTabActions.ts",
  "useFlowBuilderState.ts",
  "flowBuilderFlowActions.ts",
  "flowBuilderPublishActions.ts",
  "flowBuilderRunActions.ts",
  "flowBuilderEditorHandlers.ts",
  "useFlowBuilderCatalogs.ts",
  "flowBuilderDefaults.ts",
];

export function flowBuilderTabSource() {
  const dir = new URL("../../src/admin/components/flowBuilder/", import.meta.url);
  return FILES.map((file) => readFileSync(new URL(file, dir), "utf8")).join("\n");
}
