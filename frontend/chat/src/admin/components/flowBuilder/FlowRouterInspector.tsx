import { useState } from "react";
import type { FlowDefinitionEdge, FlowDefinitionNode } from "./flowBuilderTypes";
import { branchConnections } from "./flowBranchConnections";
import { OPERATOR_CHOICES, operatorLabel, operatorValueTypes, readRuleCondition, ruleWarnings, withCondition, type RuleCondition } from "./flowConditionalBranches";
import { withRuleBranch, type RouterRule } from "./flowRouterRule";
import { FlowRouterBranches } from "./FlowRouterBranches";
import { RuleValueEditor } from "./FlowRuleValueEditor";
import "./flowConditional.css";

type FlowRouterInspectorProps = {
  node: FlowDefinitionNode;
  onUpdate: (patch: Partial<FlowDefinitionNode>) => void;
  // The workflow's connections and steps, to show which connection each branch continues on.
  edges?: FlowDefinitionEdge[];
  nodes?: FlowDefinitionNode[];
};

const newRule = (): RouterRule => ({ route: "", when: { field: "", operator: "equals", value: "" } });

// The saved rules exactly as stored: an item that is not a rule object stays as it is (edits of
// other rules never rewrite it), and a non-list `routes` is reported instead of replaced.
function rulesFromConfig(config: Record<string, unknown> | undefined): { rules: unknown[]; notAList: boolean } {
  const raw = config?.routes;
  if (raw === undefined || raw === null) return { rules: [], notAList: false };
  return Array.isArray(raw) ? { rules: raw, notAList: false } : { rules: [], notAList: true };
}
// If / else: ordered rules, first match wins, otherwise the Otherwise branch. Each branch
// continues on the connection that names it (chosen on the connection itself).
export function FlowRouterInspector({ node, onUpdate, edges = [], nodes = [] }: FlowRouterInspectorProps) {
  const { rules, notAList } = rulesFromConfig(node.config);
  const defaultRoute = String(node.config?.default_route ?? "") || "default";
  const nodeName = (id: string) => nodes.find((item) => item.id === id)?.label || id;
  const connections = branchConnections(node.id, rules, defaultRoute, edges, nodeName);
  // Suggestions for "Value to check": the fields this step declares as its input.
  const inputFields = node.input_schema ? Object.keys(node.input_schema) : [];
  const fieldListId = `${node.id}-router-fields`;

  // Moving or removing a rule shifts rules between positions: a new layout generation gives every
  // rule editor a fresh identity, so no unfinished entry stays at a position that now shows
  // another rule. Typing never changes it. Value changes from outside (undo/redo) are synchronised
  // inside RuleValueEditor.
  const [layout, setLayout] = useState(0);
  const ruleKey = (index: number) => `${node.id}:${layout}:${index}`;
  const updateRules = (next: unknown[]) => onUpdate({ config: { ...node.config, routes: next } });
  const replaceRule = (index: number, rule: RouterRule) => updateRules(rules.map((item, itemIndex) => (itemIndex === index ? rule : item)));
  const relayout = (next: unknown[]) => {
    setLayout((value) => value + 1);
    updateRules(next);
  };
  const moveRule = (index: number, offset: number) => {
    const next = [...rules];
    const [rule] = next.splice(index, 1);
    next.splice(index + offset, 0, rule);
    relayout(next);
  };

  return (
    <div className="flow-inspector__section">
      <div className="flow-inspector__section-title">If / else</div>
      <RouterIntro node={node} notAList={notAList} inputFields={inputFields} fieldListId={fieldListId} />
      <div className="flow-router-inspector__routes">
        {rules.map((item, index) => (
          <RouterRuleCard key={ruleKey(index)} item={item} index={index} isLast={index === rules.length - 1} ruleId={ruleKey(index)}
            fieldList={inputFields.length ? fieldListId : undefined} onReplace={(rule) => replaceRule(index, rule)}
            onMove={(offset) => moveRule(index, offset)} onRemove={() => relayout(rules.filter((_, itemIndex) => itemIndex !== index))} />
        ))}
      </div>
      <RouterFooter
        node={node}
        notAList={notAList}
        hasRules={rules.length > 0}
        onAddRule={() => updateRules([...rules, newRule()])}
        onUpdate={onUpdate}
      />
      <FlowRouterBranches connections={connections} />
    </div>
  );
}

function RuleActions({
  isFirst,
  isLast,
  onMove,
  onRemove,
}: {
  isFirst: boolean;
  isLast: boolean;
  onMove: (offset: number) => void;
  onRemove: () => void;
}) {
  return (
    <div className="flow-conditional__rule-actions">
      <button type="button" className="flow-conditional__button" disabled={isFirst} onClick={() => onMove(-1)}>
        Move up
      </button>
      <button type="button" className="flow-conditional__button" disabled={isLast} onClick={() => onMove(1)}>
        Move down
      </button>
      <button type="button" className="flow-router-inspector__delete" onClick={onRemove}>
        Remove
      </button>
    </div>
  );
}

type RuleCardProps = {
  item: unknown;
  index: number;
  ruleId: string;
  fieldList: string | undefined;
  isLast: boolean;
  onReplace: (rule: RouterRule) => void;
  onMove: (offset: number) => void;
  onRemove: () => void;
};

// One rule (or a kept item that is not a rule). Both draw the same outer element, so an item that turns into a rule
// keeps its element.
function RouterRuleCard({ item, index, isLast, ruleId, fieldList, onReplace, onMove, onRemove }: RuleCardProps) {
  const actions = <RuleActions isFirst={index === 0} isLast={isLast} onMove={onMove} onRemove={onRemove} />;
  if (!item || typeof item !== "object" || Array.isArray(item)) {
    return (
      <div className="flow-router-inspector__route" data-testid="router-rule">
        <div className="flow-conditional__rule-head">
          <strong>{index === 0 ? "If" : "Else if"}</strong>
          <span className="flow-conditional__muted">Rule {index + 1}</span>
        </div>
        <code className="flow-conditional__kept">{JSON.stringify(item) ?? String(item)}</code>
        <div className="flow-conditional__note flow-conditional__note--attention">
          This is not a rule, so the workflow stops at this step with an error until it is removed. It is kept exactly as saved.
        </div>
        {actions}
      </div>
    );
  }
  const rule = item as RouterRule;
  const condition = readRuleCondition(rule);
  const warnings = ruleWarnings(condition);
  return (
    <div className="flow-router-inspector__route" data-testid="router-rule">
      <div className="flow-conditional__rule-head">
        <strong>{index === 0 ? "If" : "Else if"}</strong>
        <span className="flow-conditional__muted">Rule {index + 1}</span>
      </div>
      {condition.form === "operator" ? (
        <RuleOperatorFields rule={rule} condition={condition} ruleId={ruleId} fieldList={fieldList} onReplace={onReplace} />
      ) : condition.form === "custom" ? (
        <code className="flow-conditional__kept" data-testid="router-rule-raw">{JSON.stringify(condition.raw)}</code>
      ) : null}
      <label className="flow-inspector__schema-field">
        <span>Then continue on branch</span>
        <input
          className="flow-inspector__input"
          placeholder="e.g. large_order"
          value={rule.route !== undefined || rule.target === undefined ? String(rule.route ?? "") : String(rule.target ?? "")}
          onChange={(event) => onReplace(withRuleBranch(rule, event.target.value))}
        />
      </label>
      {warnings.map((warning) => (
        <div key={warning} className="flow-conditional__note flow-conditional__note--attention" data-testid="router-rule-warning">
          {warning}
        </div>
      ))}
      {actions}
    </div>
  );
}

function RuleOperatorFields({
  rule,
  condition,
  ruleId,
  fieldList,
  onReplace,
}: Pick<RuleCardProps, "ruleId" | "fieldList" | "onReplace"> & { rule: RouterRule; condition: Extract<RuleCondition, { form: "operator" }> }) {
  return (
    <>
      <label className="flow-inspector__schema-field">
        <span>Value to check</span>
        <input
          className="flow-inspector__input"
          list={fieldList}
          placeholder="amount or customer.tier"
          value={condition.field}
          onChange={(event) => onReplace(withCondition(rule, { field: event.target.value }))}
        />
      </label>
      <label className="flow-inspector__schema-field">
        <span>Comparison</span>
        <select
          className="flow-inspector__select"
          value={condition.operator}
          onChange={(event) => onReplace(withCondition(rule, { operator: event.target.value }))}
        >
          {!condition.operator ? <option value="">Choose a comparison…</option> : null}
          {condition.operator && !OPERATOR_CHOICES.includes(condition.operator) ? (
            <option value={condition.operator}>{operatorLabel(condition.operator)}</option>
          ) : null}
          {OPERATOR_CHOICES.map((operator) => (
            <option key={operator} value={operator}>
              {operatorLabel(operator)}
            </option>
          ))}
        </select>
      </label>
      {operatorValueTypes(condition.operator).length || condition.hasValue ? (
        <RuleValueEditor
          key={`${ruleId}:${condition.operator}`}
          condition={condition}
          onValue={(value) => onReplace(withCondition(rule, { value }))}
        />
      ) : null}
    </>
  );
}

function RouterFooter({
  node,
  notAList,
  hasRules,
  onAddRule,
  onUpdate,
}: Pick<FlowRouterInspectorProps, "node" | "onUpdate"> & { notAList: boolean; hasRules: boolean; onAddRule: () => void }) {
  return (
    <div className="flow-router-inspector__actions">
      {notAList ? null : (
        <button type="button" onClick={onAddRule}>
          {hasRules ? "Add else-if rule" : "Add a rule"}
        </button>
      )}
      <label className="flow-inspector__schema-field">
        <span>Otherwise continue on branch</span>
        <input
          className="flow-inspector__input"
          value={String(node.config?.default_route ?? "")}
          placeholder="default"
          onChange={(event) => onUpdate({ config: { ...node.config, default_route: event.target.value } })}
        />
      </label>
    </div>
  );
}

function RouterIntro({
  node,
  notAList,
  inputFields,
  fieldListId,
}: {
  node: FlowDefinitionNode;
  notAList: boolean;
  inputFields: string[];
  fieldListId: string;
}) {
  return (
    <>
      <div className="flow-inspector__hint">
        Checks the rules from top to bottom. The first rule that matches picks its branch; when none matches, the Otherwise branch
        runs. Then draw a connection from this step to the next one, select the connection and choose its branch. Steps inside an
        agent always run in order; use If / else in a workflow to choose between paths.
      </div>
      {inputFields.length ? (
        <datalist id={fieldListId}>
          {inputFields.map((field) => (
            <option key={field} value={field} />
          ))}
        </datalist>
      ) : null}
      {notAList ? (
        <div className="flow-conditional__note flow-conditional__note--attention" role="status">
          The saved rules of this step are not a list, so it cannot run. They are kept as saved: <code>{JSON.stringify(node.config?.routes)}</code>
        </div>
      ) : null}
    </>
  );
}
