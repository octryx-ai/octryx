import { useAdminNavigation } from "../../adminNavigation";
import {
  GuidedAgentField,
  GuidedBindingField,
  GuidedCapabilityField,
  GuidedPromptField,
  GuidedWorkspaceField,
  type ActionGuidedFieldsProps,
} from "./ActionGuidedFieldParts";
import "./actionGuided.css";

// Guided "Run an agent" fields. The agent itself is defined and managed only under
// Agents & workflows; this form chooses one and states what its runs will use.
export function ActionGuidedFields(props: ActionGuidedFieldsProps) {
  const { openAdminTab } = useAdminNavigation();
  const configLocked = Boolean(props.config.error);

  return (
    <div className="action-guided">
      <p className="admin-panel__hint action-guided__intro">
        This action runs one agent. Choose where it runs and which agent; the
        agent's own instructions, tools and steps apply.
      </p>

      <GuidedWorkspaceField props={props} openAdminTab={openAdminTab} />
      <GuidedAgentField props={props} openAdminTab={openAdminTab} />
      <GuidedBindingField props={props} />
      <GuidedCapabilityField props={props} configLocked={configLocked} />
      <GuidedPromptField props={props} configLocked={configLocked} />
    </div>
  );
}
