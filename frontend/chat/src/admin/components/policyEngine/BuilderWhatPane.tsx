import { useState } from "react";

import { ChipSet, FreeList, GroupLabel } from "./BuilderChips";
import type { PaneProps } from "./BuilderPanes";
import { isContentPolicy } from "./builderContentModel";
import { blockState, commandSplit, toggle, withField } from "./policyBuilderModel";

const MAX_TOOL_CHIPS = 40;

// Step 3: the actions as cards grouped like the catalog (with when they are checked, in plain language), then the detail blocks the
// chosen actions support: connector, tools, data/log calls, models, remote class, command facts with a live split
// preview, paths and client tools.
export function WhatPane({ model, onChange, catalog, entities, required }: PaneProps) {
  const [toolQuery, setToolQuery] = useState("");
  const [tryCommand, setTryCommand] = useState("kubectl --context <context> delete pod api-7f");
  const what = model.what;
  const set = (field: string, value: unknown) => onChange(withField(model, field, value));
  const shown = (block: string) => blockState(catalog, block, model.actions).state === "available";
  const familyLabel = (id: string) => entities.connectorFamilies.find((item) => item.id === id)?.label ?? id;
  const onlyGenericTools = model.actions.length > 0 && model.actions.every((action) => action === "call_tool");
  const toolPool = entities.tools.filter((tool) => (what.families.length ? what.families.includes(tool.connectorFamily)
    : onlyGenericTools ? !tool.connectorFamily : true));
  const needle = toolQuery.trim().toLowerCase();
  const tools = toolPool.filter((tool) => !needle || tool.name.toLowerCase().includes(needle)).slice(0, MAX_TOOL_CHIPS).map((tool) => tool.name);
  const coding = model.actions.some((action) => ["run_command", "read_path", "write_path"].includes(action));

  return (
    <section className="admin-panel__card policies__pane" data-testid="builder-pane-what">
      <div className="admin-panel__section-header"><span>What is blocked</span></div>
      <ActionCards model={model} catalog={catalog} onChange={onChange} />
      {!model.actions.length ? <div className="admin-panel__empty-state" data-testid="builder-no-action">Pick at least one action.</div> : null}
      <p className="admin-panel__hint">Only Call a model and Receive a tool result have content: picked alone, they add the Content and Outcome steps.</p>
      {shown("what.connector_family") ? (
        <>
          <GroupLabel>Connector</GroupLabel>
          <ChipSet options={catalog.connectorFamilies} selected={what.families} label={familyLabel} testId="builder-families"
            onToggle={(value) => set("what.families", toggle(what.families, value))} />
        </>
      ) : null}
      {shown("what.tool") ? (
        <ToolBlock what={what} pool={toolPool.length} tools={tools} query={toolQuery} onQuery={setToolQuery} set={set} />
      ) : null}
      {shown("what.writes") ? (
        <label className="policies__row policies__summary"><input type="checkbox" checked={what.writes_only} data-testid="builder-writes"
          onChange={(event) => set("what.writes_only", event.target.checked)} /> Only calls that change data</label>
      ) : null}
      {shown("what.reads_logs") ? (
        <label className="policies__row policies__summary"><input type="checkbox" checked={what.reads_logs} data-testid="builder-reads-logs"
          onChange={(event) => set("what.reads_logs", event.target.checked)} /> Only calls that read logs</label>
      ) : null}
      {shown("what.model") && !isContentPolicy(model) ? (
        <ModelBlock what={what} entities={entities} required={required} set={set} />
      ) : null}
      {shown("what.remote_class_below") ? (
        <RemoteClassBlock value={what.remote_class_below} classes={catalog.dataPolicyClasses} set={set} />
      ) : null}
      {shown("what.program") ? (
        <CommandBlock model={model} tryCommand={tryCommand} onTryCommand={setTryCommand} set={set} />
      ) : null}
      {shown("what.path_like") ? <PathBlock paths={what.paths} set={set} /> : null}
      {shown("what.client_tool") && coding ? <ClientToolsBlock options={catalog.clientTools} selected={what.client_tools} set={set} /> : null}
      {model.actions.includes("use_seat") ? <div className="policies__note">The personal seat is decided per Workspace. Choose Workspaces or a classification in the next step.</div> : null}
    </section>
  );
}

type SetField = (field: string, value: unknown) => void;

function ActionCards({ model, catalog, onChange }: Pick<PaneProps, "model" | "catalog" | "onChange">) {
  return (
    <>
      {catalog.actionGroups.map((group) => (
        <div key={group}>
          <GroupLabel>{group}</GroupLabel>
          <div className="policies__choice-grid">
            {catalog.actions.filter((action) => action.group === group).map((action) => (
              <button key={action.id} type="button" data-testid={`builder-action-${action.id}`} aria-pressed={model.actions.includes(action.id)}
                className={`policies__choice${model.actions.includes(action.id) ? " policies__choice--selected" : ""}`}
                onClick={() => onChange({ ...model, actions: catalog.actions.map((item) => item.id).filter((id) => (id === action.id ? !model.actions.includes(id) : model.actions.includes(id))) })}>
                <b>{action.label}</b>
                <small title={`Enforcement point: ${action.pointLabel}`}>{action.pointWhen || action.pointLabel}{action.carriesUser ? "" : " · does not know the user"}{action.content ? ` · content: ${action.content}` : ""}</small>
              </button>
            ))}
          </div>
        </div>
      ))}
    </>
  );
}

function ModelBlock({ what, entities, required, set }: { what: PaneProps["model"]["what"]; entities: PaneProps["entities"]; required: string[]; set: SetField }) {
  return (
    <>
      <GroupLabel>Models</GroupLabel>
      <div className="policies__row">
        <select className="admin-users__toolbar-select" value={what.model_mode} data-testid="builder-model-mode" onChange={(event) => set("what.model_mode", event.target.value)}>
          <option value="except">Block every model except</option>
          <option value="only">Block only these models</option>
        </select>
      </div>
      <ChipSet options={entities.modelAliases.map((item) => item.alias)} selected={what.models} testId="builder-models" addPlaceholder="Another model alias"
        label={(alias) => { const found = entities.modelAliases.find((item) => item.alias === alias); return found?.dataPolicyClass ? `${alias} · ${found.dataPolicyClass}` : alias; }}
        required={required.includes("what.models")} onToggle={(value) => set("what.models", toggle(what.models, value))} />
    </>
  );
}

function CommandBlock({ model, tryCommand, onTryCommand, set }: { model: PaneProps["model"]; tryCommand: string; onTryCommand: (value: string) => void; set: SetField }) {
  const what = model.what;
  return (
    <>
      <GroupLabel>Program is</GroupLabel>
      <FreeList values={what.programs} placeholder="kubectl" testId="builder-programs" onChange={(next) => set("what.programs", next)} />
      <GroupLabel>Command starts with</GroupLabel>
      <FreeList values={what.prefixes} placeholder="kubectl delete" testId="builder-prefixes" onChange={(next) => set("what.prefixes", next)} />
      <div className="policies__sub">A prefix cannot see a subcommand after options (kubectl --context x delete …); prefer program + arguments.</div>
      <GroupLabel>Has all of these arguments</GroupLabel>
      <FreeList values={what.arguments} placeholder="rollout" testId="builder-arguments" onChange={(next) => set("what.arguments", next)} />
      <GroupLabel>Has option value</GroupLabel>
      <FreeList values={what.option_values} placeholder="--namespace=<namespace>" testId="builder-option-values" onChange={(next) => set("what.option_values", next)} />
      <label className="policies__row policies__summary"><input type="checkbox" checked={what.unparseable} data-testid="builder-unparseable"
        onChange={(event) => set("what.unparseable", event.target.checked)} /> Commands that could not be parsed</label>
      <GroupLabel>Try a command</GroupLabel>
      <input className="policies__input-inline" value={tryCommand} data-testid="builder-try-command" onChange={(event) => onTryCommand(event.target.value)} />
      <div className="policies__split" data-testid="builder-command-split">
        {commandSplit(tryCommand, model).map((part, index) => (
          <span key={`${part.token}-${index}`} className={part.hit ? "policies__split-hit" : undefined}>{part.role === "program" ? "program: " : ""}{part.token}</span>
        ))}
      </div>
      <div className="policies__sub">How the check splits it: program, prefixes, arguments and option values. Highlighted tokens match this policy.</div>
    </>
  );
}

function ToolBlock({ what, pool, tools, query, onQuery, set }: {
  what: PaneProps["model"]["what"]; pool: number; tools: string[]; query: string; onQuery: (value: string) => void; set: SetField;
}) {
  return (
    <>
      <GroupLabel>Only these tools (optional)</GroupLabel>
      <input className="admin-users__toolbar-input" placeholder={`Search ${pool} tools …`} value={query} data-testid="builder-tool-search"
        onChange={(event) => onQuery(event.target.value)} />
      <ChipSet options={tools} selected={what.tools} testId="builder-tools" onToggle={(value) => set("what.tools", toggle(what.tools, value))} />
    </>
  );
}

function RemoteClassBlock({ value, classes, set }: { value: string; classes: string[]; set: SetField }) {
  return (
    <>
      <GroupLabel>Remote model's data-policy class is below</GroupLabel>
      <select className="admin-users__toolbar-select" value={value} data-testid="builder-remote-class" onChange={(event) => set("what.remote_class_below", event.target.value)}>
        <option value="">Any class</option>
        {classes.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
      <div className="policies__note">Remote embeddings and rerankers are identified by kind and data-policy class. Restrict them by Workspace classification in the next step.</div>
    </>
  );
}

function PathBlock({ paths, set }: { paths: string[]; set: SetField }) {
  return (
    <>
      <GroupLabel>Path matches</GroupLabel>
      <FreeList values={paths} placeholder="*.env" testId="builder-paths" onChange={(next) => set("what.paths", next)} />
      <div className="policies__sub">* matches any characters including "/". ? and [..] are not supported.</div>
    </>
  );
}

function ClientToolsBlock({ options, selected, set }: { options: string[]; selected: string[]; set: SetField }) {
  return (
    <>
      <GroupLabel>Client tool is (optional)</GroupLabel>
      <ChipSet options={options} selected={selected} testId="builder-client-tools" onToggle={(value) => set("what.client_tools", toggle(selected, value))} />
    </>
  );
}
