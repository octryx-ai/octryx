// The standard Jira write-back a Workspace starts from: which
// status in the source, transition, labels and comment each Work state writes back (neutral names, backend;
// the server keeps the Jira names beside them). Created in dry-run mode.
export const DEFAULT_WORKFLOW_PAYLOAD = {
  name: "Standard secure development workflow",
  description: "Default Work Item state flow with Jira sync-back preview mappings.",
  is_default: true,
  states: [
    { key: "intake", label: "Intake" },
    { key: "clarification", label: "Clarification" },
    { key: "ready_for_development", label: "Ready for development" },
    { key: "development", label: "Development" },
    { key: "validation", label: "Validation" },
    { key: "review", label: "Review" },
    { key: "done", label: "Done" },
    { key: "blocked", label: "Blocked" },
  ],
  mappings: {
    clarification: {
      source_status: "Clarification",
      source_transition: "Request clarification",
      comment_template: "Octryx needs clarification before implementation can continue.",
      labels: ["octryx-clarification"],
      sync_back: true,
    },
    ready_for_development: {
      source_status: "Ready for Development",
      source_transition: "Approve for development",
      labels: ["octryx-ready"],
      sync_back: true,
    },
    development: {
      source_status: "In Progress",
      source_transition: "Start progress",
      labels: ["octryx-development"],
      sync_back: true,
    },
    validation: {
      source_status: "Validation",
      source_transition: "Start validation",
      labels: ["octryx-validation"],
      sync_back: true,
    },
    done: {
      source_status: "Done",
      source_transition: "Resolve issue",
      labels: ["octryx-done"],
      sync_back: true,
    },
  },
};
