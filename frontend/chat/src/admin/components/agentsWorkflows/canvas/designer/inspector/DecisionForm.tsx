// Inspector form for a condition: what it looks at and where each of its results leads.
import type { ReactNode } from "react";
import type { DefEdge, DefNode } from "../types";
import { OTHERWISE, resultValues, routableSources } from "./exitValues";
import { CheckList, NumberField, Problems, SelectField, TextField } from "./fields";
import { boxName, strings, text, type FormProps } from "./inspectorValues";
import { OPERATORS_BY_KIND, exitName, kindName, operatorName } from "./labels";
import { issuesAt } from "./patch";

/** "Passed → [box]": where one result of a condition leads. */
function RouteRow({ label, when, node, nodes, edges, editable, onRoute, onChosen, warn, fallback }: {
  label: string; when: string; node: DefNode; nodes: DefNode[]; edges: DefEdge[]; editable: boolean;
  onRoute?: (when: string, target: string | null) => void; onChosen?: (target: string | null) => void; warn?: string;
  /** The box the condition's "Otherwise" leads to: an unused result goes there. */
  fallback?: string;
}) {
  const edge = edges.find((item) => item.source === node.id && item.kind === "next" && item.when === when);
  const target = nodes.find((item) => item.id === edge?.target);
  const targets = nodes.filter((item) => item.id !== node.id && item.type !== "start");
  return (
    <div className="dsi-routerow">
      <span className="dsi-routerow__when">{label}</span>
      <span className="dsi-routerow__arrow" aria-hidden="true">→</span>
      {onRoute && editable ? (
        <select className="admin-panel__input" value={edge?.target ?? ""} aria-label={`Where the run goes: ${label}`}
          aria-invalid={Boolean(warn)}
          onChange={(event) => { const next = event.target.value || null; onChosen?.(next); onRoute(when, next); }}>
          <option value="">{when === OTHERWISE ? "No fallback" : fallback ? `Like otherwise (${fallback})` : "Not used"}</option>
          {targets.map((item) => <option key={item.id} value={item.id}>{boxName(item)}</option>)}
        </select>
      ) : (
        <span className="dsi-routerow__target">
          {target ? boxName(target) : fallback && when !== OTHERWISE ? `Like otherwise (${fallback})` : "Not connected yet: draw an arrow on the canvas."}
        </span>
      )}
      {warn ? <span className="dsi-problem dsi-routerow__warn" role="alert">{warn}</span> : null}
    </div>
  );
}

type DecisionParts = FormProps & {
  config: Record<string, unknown>;
  routeHere: (when: string) => boolean;
  modeField: ReactNode;
};

/** A condition on a ticket field: the field, the comparison and value, and where yes and otherwise lead. */
function FieldDecisionForm({
  node, nodes, edges, catalog, editable, issues, set, replace, onRoute, config, routeHere, modeField,
}: DecisionParts) {
  const fields = catalog.workItemFields ?? [];
  const field = fields.find((item) => item.key === text(config.field));
  const operators = field ? OPERATORS_BY_KIND[field.kind] ?? [] : [];
  return (
    <>
      {modeField}
      <SelectField label="Field" value={text(config.field)} disabled={!editable} issues={issuesAt(issues, "config.field")}
        options={fields.map((item) => ({ value: item.key, label: item.label }))}
        onChange={(key) => {
          const next = fields.find((item) => item.key === key);
          replace({ check: "field", field: key, operator: next ? (OPERATORS_BY_KIND[next.kind] ?? [])[0] ?? "" : "", value: "" });
        }} />
      {field ? (
        <div className="dsi-compare">
          <SelectField label="Comparison" value={text(config.operator)} disabled={!editable}
            issues={issuesAt(issues, "config.operator")}
            options={operators.map((value) => ({ value, label: operatorName(value) }))}
            onChange={(operator) => set("operator", operator)} />
          {field.kind === "enum" && field.values?.length ? (
            <SelectField label="Value" value={text(config.value)} disabled={!editable} issues={issuesAt(issues, "config.value")}
              options={field.values.map((value) => ({ value, label: value }))} onChange={(value) => set("value", value)} />
          ) : field.kind === "number" ? (
            <NumberField label="Value" value={typeof config.value === "number" ? config.value : null} disabled={!editable}
              issues={issuesAt(issues, "config.value")} onChange={(value) => set("value", value ?? "")} />
          ) : (
            <TextField label="Value" value={text(config.value)} disabled={!editable} issues={issuesAt(issues, "config.value")}
              placeholder={field.kind === "list" ? "e.g. regression" : undefined} onChange={(value) => set("value", value)} />
          )}
        </div>
      ) : null}
      <section className="dsi-group" aria-label="Where the run goes">
        <h4 className="dsi-group__title">Where the run goes</h4>
        <div className="dsi-routes">
        <RouteRow label="Yes" when="yes" node={node} nodes={nodes} edges={edges} editable={editable} onRoute={onRoute}
          warn={routeHere("yes") ? undefined : "Choose where the run goes when the comparison is true."} />
        <RouteRow label="Otherwise" when="no" node={node} nodes={nodes} edges={edges} editable={editable} onRoute={onRoute}
          warn={routeHere("no") ? undefined : "Choose where the run goes otherwise."} />
        </div>
      </section>
    </>
  );
}

/** A condition on a step's result: the step, the results it branches on and where each leads. */
function ResultDecisionForm({
  node, nodes, edges, catalog, editable, issues, set, onRoute, config, routeHere, modeField,
}: DecisionParts) {
  const source = nodes.find((item) => item.id === text(config.source));
  const values = source ? resultValues(source, catalog) : [];
  const options = strings(config.options);
  const stale = options.filter((value) => !values.includes(value));
  const unrouted = values.filter((value) => !options.includes(value));
  const hasFallback = routeHere(OTHERWISE);
  const fallbackEdge = edges.find((item) => item.source === node.id && item.kind === "next" && item.when === OTHERWISE);
  const fallback = boxName(nodes.find((item) => item.id === fallbackEdge?.target)) || undefined;
  return (
    <>
      {modeField}
      <SelectField label={modeField ? "Step" : "Looks at the result of"} value={text(config.source)}
        disabled={!editable} issues={issuesAt(issues, "config.source")}
        hint={routableSources(nodes, node.id, catalog).length ? undefined
          : "No box has results yet. For an agent step, add “Possible results”."}
        options={routableSources(nodes, node.id, catalog).map((item) => ({
          value: item.id, label: `${boxName(item)} (${kindName(item.type)})` }))}
        onChange={(id) => set("source", id) /* options stay; problems show if they no longer fit */} />
      {source ? (
        <section className="dsi-group" aria-label="Where the run goes">
          <h4 className="dsi-group__title">Where the run goes</h4>
          {onRoute ? null : (
            <CheckList label="Branches on" values={options} disabled={!editable}
              options={values.map((value) => ({ value, label: exitName(value) }))}
              gone={(value) => `${exitName(value)} (never happens here: untick it)`}
              onChange={(next) => set("options", next)} />
          )}
          <div className="dsi-routes">
          {values.map((value) => (
            <RouteRow key={value} label={exitName(value)} when={value} node={node} nodes={nodes} edges={edges}
              editable={editable} onRoute={onRoute} fallback={fallback}
              onChosen={(target) => set("options", target
                ? [...options.filter((item) => item !== value), value]
                : options.filter((item) => item !== value))}
              warn={options.includes(value) && !routeHere(value) ? "Choose where the run goes." : undefined} />
          ))}
          <RouteRow label="Otherwise" when={OTHERWISE} node={node} nodes={nodes} edges={edges} editable={editable}
            onRoute={onRoute}
            warn={unrouted.length && !hasFallback
              ? `${unrouted.map(exitName).join(", ")} ${unrouted.length === 1 ? "has" : "have"} no way: choose a box or a fallback.`
              : undefined} />
          {stale.map((value) => (
            <RouteRow key={value} label={`${exitName(value)} (never happens)`} when={value} node={node} nodes={nodes} edges={edges}
              editable={editable} onRoute={onRoute} onChosen={() => set("options", options.filter((item) => item !== value))}
              warn={`${boxName(source)} never ends with ${exitName(value)}: choose “Not used”.`} />
          ))}
          </div>
          {stale.length ? null : <Problems issues={issuesAt(issues, "config.options")} />}
        </section>
      ) : null}
    </>
  );
}

export function DecisionForm(props: FormProps) {
  const { node, edges, catalog, editable, replace } = props;
  const config = node.config ?? {};
  const fields = catalog.workItemFields ?? [];
  const mode = config.check === "field" ? "field" : "result";
  const routeHere = (when: string) => edges.some((item) => item.source === node.id && item.kind === "next" && item.when === when);
  const modeField = fields.length || mode === "field" ? (
    <SelectField label="Looks at" value={mode} disabled={!editable}
      options={[{ value: "result", label: "The result of a step" }, { value: "field", label: "A field of the ticket" }]}
      onChange={(next) => replace(next === "field" ? { check: "field", field: "", operator: "", value: "" } : { source: "", options: [] })} />
  ) : null;
  const parts = { ...props, config, routeHere, modeField };
  return mode === "field" ? <FieldDecisionForm {...parts} /> : <ResultDecisionForm {...parts} />;
}
