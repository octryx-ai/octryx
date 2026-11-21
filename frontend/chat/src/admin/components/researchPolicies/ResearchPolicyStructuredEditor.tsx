import {
  formatPolicySpec,
  getSpecPath,
  parsePolicySpecDraft,
  stringAt,
  textToList,
  updateSpecPath,
} from "./researchPolicySpecHelpers";
import { ResearchPolicyArchiveSection } from "./ResearchPolicyArchiveSection";
import { ResearchPolicyLiteratureSection } from "./ResearchPolicyLiteratureSection";
import { ResearchPolicySourceLimitsSection } from "./ResearchPolicySourceLimitsSection";
import { ResearchPolicyStrategySection } from "./ResearchPolicyStrategySection";

type ResearchPolicyStructuredEditorProps = {
  specDraft: string;
  onSpecDraftChange: (value: string) => void;
};

export function ResearchPolicyStructuredEditor({
  specDraft,
  onSpecDraftChange,
}: ResearchPolicyStructuredEditorProps) {
  let spec: Record<string, unknown> = {};
  let parseError = "";
  try {
    spec = parsePolicySpecDraft(specDraft);
  } catch (error) {
    parseError = error instanceof Error ? error.message : "Invalid JSON spec.";
  }

  const setPath = (path: string[], value: unknown) => {
    if (parseError) return;
    onSpecDraftChange(formatPolicySpec(updateSpecPath(spec, path, value)));
  };
  const setNumberPath = (path: string[], value: string, fallback = 0) => {
    const parsed = Number(value);
    setPath(path, Number.isFinite(parsed) ? parsed : fallback);
  };
  const setListPath = (path: string[], value: string) =>
    setPath(path, textToList(value));

  const literaturePolicy = getSpecPath(spec, [
    "source_policy",
    "literature_policy",
  ]);
  const archiveFolder =
    stringAt(spec, ["evidence_archive", "workspace_folder"], "research") ||
    "research";

  return (
    <div className="research-policy-admin__structured-editor">
      {parseError ? (
        <div className="research-policy-admin__diagnostics research-policy-admin__diagnostics--error">
          {parseError}
        </div>
      ) : null}

      <ResearchPolicyStrategySection
        spec={spec}
        parseError={parseError}
        setPath={setPath}
        setNumberPath={setNumberPath}
      />

      <ResearchPolicySourceLimitsSection spec={spec} setPath={setPath} />

      <ResearchPolicyLiteratureSection
        spec={spec}
        literaturePolicy={literaturePolicy}
        setPath={setPath}
        setListPath={setListPath}
      />

      <ResearchPolicyArchiveSection
        spec={spec}
        archiveFolder={archiveFolder}
        setPath={setPath}
      />
    </div>
  );
}
