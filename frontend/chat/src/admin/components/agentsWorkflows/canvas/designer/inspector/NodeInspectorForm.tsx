// The inspector form for one box, chosen by the box's kind.
import { CheckList, JsonObjectField, SelectField, Technical, TextField } from "./fields";
import { ChecksEditor } from "./InspectorListEditors";
import { objects, record, strings, text, toolChoices, type FormProps } from "./inspectorValues";
import { conditionName, deciderName, outcomeName, subjectName } from "./labels";
import { ON_OPEN_HIGH_KEY, ON_OPEN_HIGH_LABEL, onOpenHighChoices } from "./onOpenHigh";
import { issuesAt } from "./patch";
import { DecisionForm } from "./DecisionForm";
import { ParallelWorkForm } from "./ParallelWorkForm";
import { PhaseForm } from "./PhaseForm";

/** What a gate checks and whose work it looks at. */
function GateForm({ node, nodes, catalog, editable, issues, set }: FormProps) {
  const config = node.config ?? {};
  return (
    <>
      <ChecksEditor checks={objects(config.checks)} base="config.checks" tools={toolChoices(catalog)} title="What this box checks"
        empty="Add at least one check. Its result decides which way the run goes."
        types={catalog.gateCheckTypes.map((type) => ({
          type, label: catalog.checkTypes.find((item) => item.type === type)?.label ?? type.replace(/_/g, " "),
          params: catalog.checkTypes.find((item) => item.type === type)?.params ?? [],
        }))}
        editable={editable} issues={issuesAt(issues, "config.checks")} set={(checks) => set("checks", checks)} />
      <SelectField label="Looks at the work of (optional)" value={text(config.phase)} disabled={!editable}
        empty="The agent step right before" issues={issuesAt(issues, "config.phase")}
        options={nodes.filter((item) => item.type === "phase").map((item) => ({ value: item.id, label: item.label || item.id }))}
        onChange={(phase) => set("phase", phase || undefined)} />
    </>
  );
}

/** Who approves and what they approve. */
function ApprovalForm({ node, catalog, editable, issues, set }: FormProps) {
  const config = node.config ?? {};
  return (
    <>
      <SelectField label="Who decides" value={text(config.decider) || "requester"} disabled={!editable}
        issues={issuesAt(issues, "config.decider")}
        hint="Whoever decides, the server makes sure it is not the same person who asked (four eyes)."
        options={(catalog.deciders.length ? catalog.deciders : ["requester"]).map((value) => ({ value, label: deciderName(value) }))}
        onChange={(value) => set("decider", value)} />
      <TextField label="What is approved" value={text(config.title)} disabled={!editable}
        placeholder="e.g. Merge the fix" issues={issuesAt(issues, "config.title")} onChange={(value) => set("title", value)} />
      <TextField label="What the person should know (optional)" value={text(config.summary)} disabled={!editable}
        multiline issues={issuesAt(issues, "config.summary")} onChange={(value) => set("summary", value || undefined)} />
    </>
  );
}

/** What the person confirms and what happens when the confirmation is opened with high findings. */
function ConfirmationForm({ node, catalog, editable, issues, set, workflowKey }: FormProps) {
  const config = node.config ?? {};
  const openHigh = onOpenHighChoices(workflowKey);
  return (
    <>
      <SelectField label="The person confirms" value={text(config.subject)} disabled={!editable}
        issues={issuesAt(issues, "config.subject")}
        options={catalog.confirmationSubjects.map((value) => ({ value, label: subjectName(value) }))}
        onChange={(value) => set("subject", value)} />
      <SelectField label={ON_OPEN_HIGH_LABEL} value={text(config[ON_OPEN_HIGH_KEY])} disabled={!editable}
        empty={openHigh.empty} options={openHigh.options} issues={issuesAt(issues, `config.${ON_OPEN_HIGH_KEY}`)}
        onChange={(value) => set(ON_OPEN_HIGH_KEY, value || undefined)} />
    </>
  );
}

/** A platform action, or a tool with its arguments. */
function PlatformActionForm({ node, catalog, editable, issues, set }: FormProps) {
  const config = node.config ?? {};
  return (
    <>
      <SelectField label="What the platform does" value={text(config.action)} disabled={!editable}
        issues={issuesAt(issues, "config.action")} empty={text(config.tool) ? "A tool (see Technical details)" : "Choose…"}
        options={catalog.platformActions.map((item) => ({ value: item.key, label: item.label }))}
        onChange={(action) => set("action", action || undefined)} />
      <Technical open={!text(config.action) && Boolean(text(config.tool))}>
        <SelectField label="Or run this tool" value={text(config.tool)} disabled={!editable || Boolean(text(config.action))}
          empty="No tool" options={toolChoices(catalog)}
          issues={issuesAt(issues, "config.tool")} onChange={(tool) => set("tool", tool || undefined)} />
        <JsonObjectField label="With these arguments" value={record(config.arguments)} disabled={!editable}
          issues={issuesAt(issues, "config.arguments")} onChange={(value) => set("arguments", value)} />
      </Technical>
    </>
  );
}

export function Form(props: FormProps) {
  const { node, nodes, catalog, editable, issues, set } = props;
  const config = node.config ?? {};
  switch (node.type) {
    case "phase":
      return <PhaseForm {...props} />;
    case "decision":
      return <DecisionForm {...props} />;
    case "gate":
      return <GateForm {...props} />;
    case "approval":
      return <ApprovalForm {...props} />;
    case "user_confirmation":
      return <ConfirmationForm {...props} />;
    case "user_conversation":
      return (
        <TextField label="The question" value={text(config.question)} disabled={!editable} multiline
          placeholder="e.g. Which branch should the pull request target?" issues={issuesAt(issues, "config.question")}
          onChange={(value) => set("question", value)} />
      );
    case "watch":
      return (
        <CheckList label="Waits until" values={strings(config.conditions)} disabled={!editable}
          issues={issuesAt(issues, "config.conditions")} hint="Each event gets its own way out."
          options={catalog.watchConditions.map((value) => ({ value, label: conditionName(value) }))}
          gone={(value) => `${conditionName(value)} (not known any more: untick it)`}
          onChange={(conditions) => set("conditions", conditions)} />
      );
    case "platform_action":
      return <PlatformActionForm {...props} />;
    case "sub_workflow":
      return (
        <SelectField label="Runs the workflow" value={text(config.workflow_key)} disabled={!editable}
          issues={issuesAt(issues, "config.workflow_key")} hint="Its end decides which way this box goes on."
          options={catalog.workflows.map((item) => ({ value: item.key, label: item.title }))}
          onChange={(key) => set("workflow_key", key)} />
      );
    case "outcome":
      return (
        <SelectField label="The workflow ends as" value={text(config.outcome)} disabled={!editable}
          issues={issuesAt(issues, "config.outcome")}
          options={catalog.outcomes.map((value) => ({ value, label: outcomeName(value) }))}
          onChange={(value) => set("outcome", value)} />
      );
    case "parallel_work":
      return <ParallelWorkForm node={node} nodes={nodes} catalog={catalog} editable={editable} issues={issues} set={set} />;
    case "start":
      return <p className="admin-panel__hint">The workflow begins here. Connect it to the first box.</p>;
    case "pause":
      return <p className="admin-panel__hint">The run waits here until a person continues it.</p>;
    case "review":
      return <p className="admin-panel__hint">A second agent reviews the work independently. Its settings come later.</p>;
    default:
      return null;
  }
}
