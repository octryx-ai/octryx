import { useEffect, useRef, useState } from "react";

import { GroupLabel } from "./BuilderChips";
import type { PaneProps } from "./BuilderPanes";
import { previewContent } from "./builderContentApi";
import { EMPTY_CONTENT_PREVIEW, contentAction, detectorGroups, previewMark, readContentPreview, routes, toggleDetector } from "./builderContentModel";
import type { ContentPreview, DetectorCatalog } from "./builderContentModel";
import { refusalText } from "./policyEngineVersions";

// Step "Content": what the scan must find. Detector cards grouped by category with their hits in the
// example, "Also when" (the conversation already contained the category — only with a route; the scan could not
// finish), and the example box. The example is synthetic, stays in this pane (never in the model) and is checked
// by the server preview; the browser never detects anything itself.
export function ContentPane({ model, onChange, catalog, entities, required, detectors, previewDelay = 300 }: PaneProps & { detectors: DetectorCatalog; previewDelay?: number }) {
  const [sample, setSample] = useState("");
  const [preview, setPreview] = useState<ContentPreview>(EMPTY_CONTENT_PREVIEW);
  const [problem, setProblem] = useState<string | null>(null);
  const ticket = useRef(0);
  const content = model.content;
  const set = (patch: Partial<typeof content>) => onChange({ ...model, content: { ...content, ...patch } });
  const action = catalog.actions.find((item) => item.id === contentAction(model));
  const canStick = routes(model.outcome.kind);

  useEffect(() => {
    const current = ++ticket.current;
    if (!sample.trim()) {
      setPreview(EMPTY_CONTENT_PREVIEW);
      setProblem(null);
      return;
    }
    const timer = setTimeout(() => {
      void previewContent(sample, content.detectors, model.outcome.mask_style)
        .then((raw) => { if (current === ticket.current) { setPreview(readContentPreview(raw)); setProblem(null); } })
        .catch((error) => { if (current === ticket.current) setProblem(refusalText(error)); });
    }, previewDelay);
    return () => clearTimeout(timer);
  }, [sample, content.detectors, model.outcome.mask_style, previewDelay]);

  return (
    <section className="admin-panel__card policies__pane" data-testid="builder-pane-content">
      <div className="admin-panel__section-header"><span>When the content contains …</span>
        {action ? <span className="work-badge work-badge--neutral">{action.label}</span> : null}</div>
      <p className="admin-panel__hint">Pick what the scan must find. Detectors in one list are OR-joined; the counts show hits in the example below.</p>
      {detectorGroups(detectors).map(({ category, detectors: items }) => (
        <div key={category.id}>
          <GroupLabel>{`${category.label} · ${category.id}`}</GroupLabel>
          <div className={`policies__det-grid${required.includes("content.detectors") && !content.detectors.length ? " policies__chip--required" : ""}`}>
            {items.map((item) => {
              const on = content.detectors.includes(item.id);
              const count = preview.counts[item.id] ?? 0;
              return (
                <label key={item.id} className={`policies__det${on ? " policies__det--on" : ""}`} data-testid="builder-detector">
                  <input type="checkbox" checked={on} data-testid={`builder-detector-${item.id}`}
                    onChange={() => onChange(toggleDetector(model, item.id, detectors, entities.modelAliases))} />
                  <b>{item.label} <span className={`policies__count${count ? " policies__count--hit" : ""}`} data-testid={`builder-detector-count-${item.id}`}>{count}</span></b>
                  <span>{item.builtin ? item.method : `Custom · ${item.id}`}</span>
                </label>
              );
            })}
          </div>
        </div>
      ))}
      {!detectors.detectors.length ? <div className="admin-panel__empty-state">Loading the detectors …</div> : null}
      <GroupLabel>Also when</GroupLabel>
      <label className="policies__row policies__summary" title={canStick ? undefined : "Only with a route outcome (step Outcome)."}>
        <input type="checkbox" checked={content.sticky} disabled={!canStick} data-testid="builder-content-sticky" onChange={(event) => set({ sticky: event.target.checked })} />
        the conversation already contained this category (keeps a routed conversation on the approved model until it is cleared)
      </label>
      <label className="policies__row policies__summary">
        <input type="checkbox" checked={content.incomplete} data-testid="builder-content-incomplete" onChange={(event) => set({ incomplete: event.target.checked })} />
        the scan could not finish (over the size or time budget, or content that cannot be read, e.g. images)
      </label>
      <GroupLabel>Try it with an example (synthetic data only — never stored)</GroupLabel>
      <textarea className="policies__sample" value={sample} data-testid="builder-content-sample" spellCheck={false}
        placeholder="Paste or type synthetic text to see what the detectors find." onChange={(event) => setSample(event.target.value)} />
      {problem ? <p className="workspace-classification__message" role="alert">{problem}</p> : null}
      {preview.parts.length ? (
        <pre className="policies__masked" data-testid="builder-content-preview">
          {preview.parts.map((part, index) => {
            const { shown, mark } = previewMark(part, model);
            return mark === "none" ? <span key={index}>{shown}</span>
              : <mark key={index} className={mark === "blocked" ? "policies__mark--blocked" : undefined} title={part.detector}>{shown}</mark>;
          })}
        </pre>
      ) : null}
      <p className="admin-panel__hint">Highlighted: what this policy acts on, shown as the model would see it.{preview.truncated ? " Only the start of the example was checked." : ""}</p>
    </section>
  );
}
