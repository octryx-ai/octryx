/** Constants for the Scenario profile builder UI. */
export const ROUTE_REASONS = [
  {
    value: "summary_aggregation",
    label: "Summary Aggregation",
    hint: "Triggered when user requests a summary or aggregation of data",
  },
  {
    value: "knowledge_presentation_request",
    label: "Knowledge Presentation",
    hint: "Triggered when user asks to present project knowledge",
  },
  {
    value: "generic_presentation_request",
    label: "Generic Presentation",
    hint: "Triggered when user requests office-style presentations",
  },
  {
    value: "admin_capability",
    label: "Admin Capability",
    hint: "Triggered for admin panel operations",
  },
  {
    value: "change_or_continuation",
    label: "Change / Continuation",
    hint: "Triggered for task changes or conversation continuations",
  },
  {
    value: "admin_control",
    label: "Admin Control",
    hint: "Triggered for light admin control operations",
  },
  {
    value: "trivial_new_thread",
    label: "Trivial / New Thread",
    hint: "Triggered for simple questions in a new thread",
  },
] as const;

export const TOOL_DOMAINS = [
  {
    value: "jira",
    label: "Jira",
    hint: "Issue tracking and project management",
  },
  {
    value: "bitbucket",
    label: "Bitbucket",
    hint: "Git repositories, pull requests, and code review",
  },
  {
    value: "confluence",
    label: "Confluence",
    hint: "Documentation and wiki pages",
  },
  {
    value: "observability",
    label: "Observability",
    hint: "Metrics, logs, and monitoring data",
  },
  {
    value: "kubernetes",
    label: "Kubernetes",
    hint: "K8s cluster management and deployment",
  },
  {
    value: "office",
    label: "Office",
    hint: "Presentation and document creation (PowerPoint, Word, Excel)",
  },
] as const;

export const CONTEXT_TOGGLES = [
  {
    key: "include_skills",
    label: "Include skills",
    hint: "Include skill definitions and metadata",
  },
  {
    key: "include_recent_history",
    label: "Include recent history",
    hint: "Load the last N messages in this session",
  },
  {
    key: "include_summary_context",
    label: "Include summary context",
    hint: "Add conversation summarization metadata",
  },
  {
    key: "include_system_context",
    label: "Include system context",
    hint: "Add system-level instructions and config",
  },
] as const;
