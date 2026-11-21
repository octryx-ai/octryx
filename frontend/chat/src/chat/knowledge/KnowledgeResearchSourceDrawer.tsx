import { useId, useState } from "react";
import { splitProducts } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeRequest";
import type { SourceRequest, TrustedSource } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeTypes";
import { FormSection } from "../../layout/FormSection";
import { SidePanel } from "../../layout/SidePanel";
import {
  MAX_PATTERN_CHARS,
  MAX_PRODUCTS,
  MAX_REASON_CHARS,
  existingEntry,
  patternProblem,
  redecisionWarning,
} from "./researchSourcePresenter";
import type { SourceDecision } from "./researchSourcePresenter";

// "Add website": a side panel over the dimmed list with labelled fields and Cancel + the
// decision as the primary action at the bottom right. What a pattern covers and what an approval means is in the
// page help.
export function KnowledgeResearchSourceDrawer({ sources, mayEditPlatform, busy, onSave, onClose }: {
  sources: TrustedSource[];
  mayEditPlatform: boolean;
  busy: boolean;
  onSave: (request: SourceRequest) => void;
  onClose: () => void;
}) {
  const id = useId();
  const [pattern, setPattern] = useState("");
  const [decision, setDecision] = useState<SourceDecision>("trusted");
  const [scope, setScope] = useState<TrustedSource["scope"]>("workspace");
  const [products, setProducts] = useState("");
  const [reason, setReason] = useState("");
  const problem = patternProblem(pattern);
  const warning = redecisionWarning(existingEntry(sources, pattern, scope), decision);
  const productList = splitProducts(products);
  const tooManyProducts = productList.length > MAX_PRODUCTS;
  const blocked = busy || Boolean(problem) || tooManyProducts || !pattern.trim();
  const submit = () => {
    if (blocked) return;
    onSave({ pattern: pattern.trim(), state: decision, scope, products: productList, reason: reason.trim() });
  };
  return (
    <SidePanel title="Add website" onClose={onClose} testId="research-add-panel"
      footer={(
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={blocked}
            onClick={submit} data-testid="research-add-submit">
            {decision === "trusted" ? "Approve website" : "Block website"}
          </button>
        </>
      )}>
      <FormSection title="Website">
        <label className="admin-panel__field" htmlFor={`${id}-pattern`}>
          <span>Website</span>
          <input id={`${id}-pattern`} className="admin-panel__input" required value={pattern} maxLength={MAX_PATTERN_CHARS}
            placeholder="docs.spring.io or github.com/spring-projects/spring-boot"
            onChange={(event) => setPattern(event.target.value)} />
          {problem ? <span className="knowledge-research__problem" role="alert">{problem}</span> : null}
        </label>
        <fieldset className="knowledge-research__decision">
          <legend>Decision</legend>
          <label className="admin-panel__checkbox"><input type="radio" name={`${id}-decision`} checked={decision === "trusted"}
            onChange={() => setDecision("trusted")} /> Approve: research may read this website</label>
          <label className="admin-panel__checkbox"><input type="radio" name={`${id}-decision`} checked={decision === "blocked"}
            onChange={() => setDecision("blocked")} /> Block: nothing reads this website</label>
        </fieldset>
        {mayEditPlatform ? (
          <label className="admin-panel__field" htmlFor={`${id}-scope`}>
            <span>Applies to</span>
            <select id={`${id}-scope`} className="admin-panel__input" value={scope}
              onChange={(event) => setScope(event.target.value as TrustedSource["scope"])}>
              <option value="workspace">This workspace</option>
              <option value="platform">All workspaces</option>
            </select>
          </label>
        ) : null}
        {warning ? <p className="knowledge-research__warning" role="status">{warning}</p> : null}
      </FormSection>
      <FormSection title="Details">
        <label className="admin-panel__field" htmlFor={`${id}-products`}>
          <span>Products (optional)</span>
          <input id={`${id}-products`} className="admin-panel__input" value={products} placeholder="Comma-separated, e.g. spring-boot"
            onChange={(event) => setProducts(event.target.value)} />
          {tooManyProducts ? <span className="knowledge-research__problem" role="alert">At most {MAX_PRODUCTS} products.</span> : null}
        </label>
        <label className="admin-panel__field" htmlFor={`${id}-reason`}>
          <span>Reason (optional)</span>
          <textarea id={`${id}-reason`} className="admin-panel__input" rows={3} value={reason} maxLength={MAX_REASON_CHARS}
            onChange={(event) => setReason(event.target.value)} />
          <span className="admin-panel__note">{reason.length}/{MAX_REASON_CHARS} characters</span>
        </label>
      </FormSection>
    </SidePanel>
  );
}
