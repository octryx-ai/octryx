// Octryx baseline policy set - generated, do not edit. Schema 2026-10-08.2.
// Classification matrix: invalid. Workspaces: 0.

// == platform ==
@id("platform:seat-permit")
permit (principal, action == Action::"use_seat", resource);

@id("platform:seat-classification-unresolved")
forbid (principal, action == Action::"use_seat", resource)
unless { context.workspace has classification };

@id("platform:seat-workspace-requires-governed-routing")
forbid (principal, action == Action::"use_seat", resource)
when { resource.requires_governed_routing };

@id("platform:seat-mode-forbidden")
forbid (principal, action == Action::"use_seat", resource)
unless { resource.seat_mode == "allowed" };

@id("platform:model-admission-unverified")
forbid (principal, action == Action::"call_model", resource)
unless { context.admission_verified };

@id("platform:model-alias-missing")
forbid (principal, action == Action::"call_model", resource)
when { resource.alias == "" };

@id("platform:remote-model-permit")
permit (principal, action in [Action::"use_reranker", Action::"use_remote_embeddings"], resource);

@id("platform:remote-model-classification-unresolved")
forbid (principal, action in [Action::"use_reranker", Action::"use_remote_embeddings"], resource)
unless { context.workspace has classification_rank };

@id("platform:remote-model-class-unknown")
forbid (principal, action in [Action::"use_reranker", Action::"use_remote_embeddings"], resource)
unless { resource has data_policy_rank };

@id("platform:remote-model-class-insufficient")
forbid (principal, action in [Action::"use_reranker", Action::"use_remote_embeddings"], resource)
when { context.workspace has classification_rank && resource has data_policy_rank && context.workspace.classification_rank > resource.data_policy_rank };

@id("platform:tool-permit")
permit (principal, action in [Action::"call_tool", Action::"read_connector", Action::"write_connector"], resource);

@id("platform:client-tool-permit")
permit (principal, action in [Action::"run_command", Action::"read_path", Action::"write_path"], resource);

@id("platform:secrets-never-leave")
forbid (principal, action == Action::"call_model", resource)
when { context.content.detected.contains("secrets") };

@id("platform:seat-route-permit")
permit (principal, action == Action::"call_model", resource)
when { context.route == "seat" };

@id("platform:tool-result-permit")
permit (principal, action == Action::"receive_tool_result", resource);

@id("platform:device-run-permit")
permit (principal, action == Action::"run_on_device", resource);

@id("platform:device-run-folder-not-allowlisted")
forbid (principal, action == Action::"run_on_device", resource)
unless { context.folder_allowlisted };

// == classification public ==
@id("classification:public:seat-not-allowed")
forbid (principal, action == Action::"use_seat", resource)
when { context.workspace has classification && context.workspace.classification == "public" };

@id("classification:public:requires-governed-routing")
forbid (principal, action == Action::"use_seat", resource)
when { context.workspace has classification && context.workspace.classification == "public" };

@id("classification:public:model-aliases")
forbid (principal, action == Action::"call_model", resource)
when { context.workspace has classification && context.workspace.classification == "public" };

@id("classification:public:reranker-forbidden")
forbid (principal, action == Action::"use_reranker", resource)
when { context.workspace has classification && context.workspace.classification == "public" };

@id("classification:public:remote-embeddings-forbidden")
forbid (principal, action == Action::"use_remote_embeddings", resource)
when { context.workspace has classification && context.workspace.classification == "public" };

@id("classification:public:connector:servicenow:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"servicenow")
when { context.workspace has classification && context.workspace.classification == "public" };

@id("classification:public:connector:jira:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"jira")
when { context.workspace has classification && context.workspace.classification == "public" };

@id("classification:public:connector:confluence:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"confluence")
when { context.workspace has classification && context.workspace.classification == "public" };

@id("classification:public:connector:kubernetes:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"kubernetes")
when { context.workspace has classification && context.workspace.classification == "public" };

@id("classification:public:connector:aws:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"aws")
when { context.workspace has classification && context.workspace.classification == "public" };

@id("classification:public:connector:bitbucket:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"bitbucket")
when { context.workspace has classification && context.workspace.classification == "public" };

@id("classification:public:device-runs-not-allowed")
forbid (principal, action == Action::"run_on_device", resource)
when { context.workspace has classification && context.workspace.classification == "public" };

// == classification internal ==
@id("classification:internal:seat-not-allowed")
forbid (principal, action == Action::"use_seat", resource)
when { context.workspace has classification && context.workspace.classification == "internal" };

@id("classification:internal:requires-governed-routing")
forbid (principal, action == Action::"use_seat", resource)
when { context.workspace has classification && context.workspace.classification == "internal" };

@id("classification:internal:model-aliases")
forbid (principal, action == Action::"call_model", resource)
when { context.workspace has classification && context.workspace.classification == "internal" };

@id("classification:internal:reranker-forbidden")
forbid (principal, action == Action::"use_reranker", resource)
when { context.workspace has classification && context.workspace.classification == "internal" };

@id("classification:internal:remote-embeddings-forbidden")
forbid (principal, action == Action::"use_remote_embeddings", resource)
when { context.workspace has classification && context.workspace.classification == "internal" };

@id("classification:internal:connector:servicenow:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"servicenow")
when { context.workspace has classification && context.workspace.classification == "internal" };

@id("classification:internal:connector:jira:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"jira")
when { context.workspace has classification && context.workspace.classification == "internal" };

@id("classification:internal:connector:confluence:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"confluence")
when { context.workspace has classification && context.workspace.classification == "internal" };

@id("classification:internal:connector:kubernetes:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"kubernetes")
when { context.workspace has classification && context.workspace.classification == "internal" };

@id("classification:internal:connector:aws:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"aws")
when { context.workspace has classification && context.workspace.classification == "internal" };

@id("classification:internal:connector:bitbucket:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"bitbucket")
when { context.workspace has classification && context.workspace.classification == "internal" };

@id("classification:internal:device-runs-not-allowed")
forbid (principal, action == Action::"run_on_device", resource)
when { context.workspace has classification && context.workspace.classification == "internal" };

// == classification confidential ==
@id("classification:confidential:seat-not-allowed")
forbid (principal, action == Action::"use_seat", resource)
when { context.workspace has classification && context.workspace.classification == "confidential" };

@id("classification:confidential:requires-governed-routing")
forbid (principal, action == Action::"use_seat", resource)
when { context.workspace has classification && context.workspace.classification == "confidential" };

@id("classification:confidential:model-aliases")
forbid (principal, action == Action::"call_model", resource)
when { context.workspace has classification && context.workspace.classification == "confidential" };

@id("classification:confidential:reranker-forbidden")
forbid (principal, action == Action::"use_reranker", resource)
when { context.workspace has classification && context.workspace.classification == "confidential" };

@id("classification:confidential:remote-embeddings-forbidden")
forbid (principal, action == Action::"use_remote_embeddings", resource)
when { context.workspace has classification && context.workspace.classification == "confidential" };

@id("classification:confidential:connector:servicenow:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"servicenow")
when { context.workspace has classification && context.workspace.classification == "confidential" };

@id("classification:confidential:connector:jira:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"jira")
when { context.workspace has classification && context.workspace.classification == "confidential" };

@id("classification:confidential:connector:confluence:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"confluence")
when { context.workspace has classification && context.workspace.classification == "confidential" };

@id("classification:confidential:connector:kubernetes:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"kubernetes")
when { context.workspace has classification && context.workspace.classification == "confidential" };

@id("classification:confidential:connector:aws:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"aws")
when { context.workspace has classification && context.workspace.classification == "confidential" };

@id("classification:confidential:connector:bitbucket:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"bitbucket")
when { context.workspace has classification && context.workspace.classification == "confidential" };

@id("classification:confidential:device-runs-not-allowed")
forbid (principal, action == Action::"run_on_device", resource)
when { context.workspace has classification && context.workspace.classification == "confidential" };

// == classification restricted ==
@id("classification:restricted:seat-not-allowed")
forbid (principal, action == Action::"use_seat", resource)
when { context.workspace has classification && context.workspace.classification == "restricted" };

@id("classification:restricted:requires-governed-routing")
forbid (principal, action == Action::"use_seat", resource)
when { context.workspace has classification && context.workspace.classification == "restricted" };

@id("classification:restricted:model-aliases")
forbid (principal, action == Action::"call_model", resource)
when { context.workspace has classification && context.workspace.classification == "restricted" };

@id("classification:restricted:reranker-forbidden")
forbid (principal, action == Action::"use_reranker", resource)
when { context.workspace has classification && context.workspace.classification == "restricted" };

@id("classification:restricted:remote-embeddings-forbidden")
forbid (principal, action == Action::"use_remote_embeddings", resource)
when { context.workspace has classification && context.workspace.classification == "restricted" };

@id("classification:restricted:connector:servicenow:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"servicenow")
when { context.workspace has classification && context.workspace.classification == "restricted" };

@id("classification:restricted:connector:jira:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"jira")
when { context.workspace has classification && context.workspace.classification == "restricted" };

@id("classification:restricted:connector:confluence:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"confluence")
when { context.workspace has classification && context.workspace.classification == "restricted" };

@id("classification:restricted:connector:kubernetes:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"kubernetes")
when { context.workspace has classification && context.workspace.classification == "restricted" };

@id("classification:restricted:connector:aws:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"aws")
when { context.workspace has classification && context.workspace.classification == "restricted" };

@id("classification:restricted:connector:bitbucket:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"bitbucket")
when { context.workspace has classification && context.workspace.classification == "restricted" };

@id("classification:restricted:device-runs-not-allowed")
forbid (principal, action == Action::"run_on_device", resource)
when { context.workspace has classification && context.workspace.classification == "restricted" };

// == classification secret ==
@id("classification:secret:seat-not-allowed")
forbid (principal, action == Action::"use_seat", resource)
when { context.workspace has classification && context.workspace.classification == "secret" };

@id("classification:secret:requires-governed-routing")
forbid (principal, action == Action::"use_seat", resource)
when { context.workspace has classification && context.workspace.classification == "secret" };

@id("classification:secret:model-aliases")
forbid (principal, action == Action::"call_model", resource)
when { context.workspace has classification && context.workspace.classification == "secret" };

@id("classification:secret:reranker-forbidden")
forbid (principal, action == Action::"use_reranker", resource)
when { context.workspace has classification && context.workspace.classification == "secret" };

@id("classification:secret:remote-embeddings-forbidden")
forbid (principal, action == Action::"use_remote_embeddings", resource)
when { context.workspace has classification && context.workspace.classification == "secret" };

@id("classification:secret:connector:servicenow:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"servicenow")
when { context.workspace has classification && context.workspace.classification == "secret" };

@id("classification:secret:connector:jira:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"jira")
when { context.workspace has classification && context.workspace.classification == "secret" };

@id("classification:secret:connector:confluence:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"confluence")
when { context.workspace has classification && context.workspace.classification == "secret" };

@id("classification:secret:connector:kubernetes:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"kubernetes")
when { context.workspace has classification && context.workspace.classification == "secret" };

@id("classification:secret:connector:aws:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"aws")
when { context.workspace has classification && context.workspace.classification == "secret" };

@id("classification:secret:connector:bitbucket:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"bitbucket")
when { context.workspace has classification && context.workspace.classification == "secret" };

@id("classification:secret:device-runs-not-allowed")
forbid (principal, action == Action::"run_on_device", resource)
when { context.workspace has classification && context.workspace.classification == "secret" };
