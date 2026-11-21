import { GroupLabel } from "./BuilderChips";
import type { PaneProps } from "./BuilderPanes";
import { approvedAliases, categoriesOf, contentAction, masks, outcomeRefusal, readOutcomeKind, routes, withOutcome } from "./builderContentModel";
import type { DetectorCatalog } from "./builderContentModel";

// Step "Outcome": Block · Mask · Route to an approved model · Mask and route (routing is refused for tool
// results, with the reason). A route offers only the aliases approved for every category the detectors name (the
// others are shown disabled, "not approved"), and states when the request is blocked instead. Masking picks the
// style; Mask on a model request can except the models approved for the categories.
export function OutcomePane({ model, onChange, catalog, entities, required, detectors }: PaneProps & { detectors: DetectorCatalog }) {
  const outcome = model.outcome;
  const action = contentAction(model);
  const categories = categoriesOf(model.content.detectors, detectors);
  const categoryText = categories.join(", ") || "the chosen detectors' categories";
  const set = (patch: Partial<typeof outcome>) => onChange({ ...model, outcome: { ...outcome, ...patch } });
  const aliases = approvedAliases(entities.modelAliases, categories);
  return (
    <section className="admin-panel__card policies__pane" data-testid="builder-pane-outcome">
      <div className="admin-panel__section-header"><span>Then …</span></div>
      <div className="policies__choice-grid">
        {catalog.outcomes.map((item) => {
          const kind = readOutcomeKind(item.id);
          const refusal = outcomeRefusal(kind, action);
          return (
            <button key={item.id} type="button" disabled={Boolean(refusal)} data-testid={`builder-outcome-${item.id}`} aria-pressed={outcome.kind === kind}
              className={`policies__choice${outcome.kind === kind ? " policies__choice--selected" : ""}${refusal ? " policies__chip-off" : ""}`}
              onClick={() => onChange(withOutcome(model, kind))}>
              <b>{item.label}</b><span>{item.description}</span>{refusal ? <small>{refusal}</small> : null}
            </button>
          );
        })}
      </div>
      {routes(outcome.kind) ? (
        <>
          <GroupLabel>Approved model</GroupLabel>
          <div className="policies__chips" data-testid="builder-route-targets">
            {aliases.map((item) => {
              const selected = outcome.reroute_to === item.alias;
              return (
                <button key={item.alias} type="button" disabled={!item.approved} aria-pressed={selected} data-testid="builder-route-target" data-value={item.alias}
                  title={item.approved ? `approved for ${item.approvedFor.join(", ")}` : `not approved for ${categoryText}`}
                  className={`admin-policy-chip${selected ? "" : " admin-policy-chip--secondary"}${item.approved ? "" : " policies__chip-off"}${required.includes("outcome.reroute_to") && !outcome.reroute_to ? " policies__chip--required" : ""}`}
                  onClick={() => set({ reroute_to: selected ? "" : item.alias })}>
                  {item.alias}{item.dataPolicyClass ? ` · ${item.dataPolicyClass}` : ""}{item.approved ? "" : " — not approved"}
                </button>
              );
            })}
          </div>
          {!aliases.length ? <div className="policies__sub">No model gateway alias is configured yet.</div> : null}
          <p className="admin-panel__hint">Only aliases approved for <b>{categoryText}</b> are offered (Settings → Model gateway aliases → Approved for sensitive data).</p>
          <div className="policies__note" data-testid="builder-route-note">
            A routed seat request is served on the governed route with the platform's credentials (the seat token is not forwarded) and counts against the
            Workspace budget. It is <b>blocked instead</b> when the approved model is not admitted in the Workspace, lacks tool support, has a smaller context
            than the request, or the budget is exhausted — never sent to the seat.
          </div>
        </>
      ) : null}
      {masks(outcome.kind) ? (
        <>
          <GroupLabel>Mask style</GroupLabel>
          <select className="admin-users__toolbar-select" value={outcome.mask_style || "type_token"} data-testid="builder-mask-style" onChange={(event) => set({ mask_style: event.target.value })}>
            {catalog.maskStyles.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
          <p className="admin-panel__hint">Masking is one-way: placeholders are numbered per conversation (the same value gets the same number) but can never be turned back.</p>
        </>
      ) : null}
      {outcome.kind === "mask" && action === "call_model" ? (
        <label className="policies__row policies__summary">
          <input type="checkbox" checked={outcome.approved_except} data-testid="builder-approved-except" onChange={(event) => set({ approved_except: event.target.checked })} />
          Except models approved for {categoryText} (they receive the data unmasked)
        </label>
      ) : null}
    </section>
  );
}

// Check & save, for a content policy: the checks the save repeats (schema and obligation annotations, the route
// target approved for the categories). Simulated-scan examples are not generated: the test bench cannot ask with a
// scan result yet.
export function ContentChecks({ model, valid, aliases, detectors }: { model: PaneProps["model"]; valid: boolean; aliases: PaneProps["entities"]["modelAliases"]; detectors: DetectorCatalog }) {
  const categories = categoriesOf(model.content.detectors, detectors);
  const target = aliases.find((item) => item.alias === model.outcome.reroute_to);
  const approved = Boolean(target) && categories.every((category) => target?.approvedFor.includes(category));
  const route = !routes(model.outcome.kind) ? <span>✓ no route target needed</span>
    : !model.outcome.reroute_to ? <span className="policies__check--bad">✗ pick an approved model</span>
      : approved ? <span>✓ {model.outcome.reroute_to} is approved for {categories.join(", ")}</span>
        : <span className="policies__check--bad">✗ {model.outcome.reroute_to} is not approved for {categories.join(", ")}</span>;
  return (
    <section className="admin-panel__card policies__pane" data-testid="builder-content-checks">
      <div className="admin-panel__section-header"><span>Content checks</span></div>
      <div className="policies__summary">
        {valid ? "✓ Validates against the schema · ✓ obligation annotations valid" : <span className="policies__check--bad">✗ Not valid yet</span>} · {route}
      </div>
      <p className="admin-panel__hint">Saving checks them again: the route target must be an alias of an active model gateway approved for every category the policy names.</p>
    </section>
  );
}
