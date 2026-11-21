// Octryx baseline policy set - generated, do not edit. Schema 2026-10-08.2.
// Classification matrix: configured. Workspaces: 2.

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
@id("classification:public:requires-governed-routing")
forbid (principal, action == Action::"use_seat", resource)
when { context.workspace has classification && context.workspace.classification == "public" };

@id("classification:public:remote-embeddings-forbidden")
forbid (principal, action == Action::"use_remote_embeddings", resource)
when { context.workspace has classification && context.workspace.classification == "public" };

// == classification internal ==
@id("classification:internal:model-aliases")
forbid (principal, action == Action::"call_model", resource)
when { context.workspace has classification && context.workspace.classification == "internal" && !["octryx-sonnet"].contains(resource.alias) };

@id("classification:internal:connector:jira:read-only")
forbid (principal, action == Action::"write_connector", resource in ConnectorFamily::"jira")
when { context.workspace has classification && context.workspace.classification == "internal" };

@id("classification:internal:connector:kubernetes:none")
forbid (principal, action in [Action::"read_connector", Action::"write_connector"], resource in ConnectorFamily::"kubernetes")
when { context.workspace has classification && context.workspace.classification == "internal" };

// == classification confidential ==
@id("classification:confidential:seat-not-allowed")
forbid (principal, action == Action::"use_seat", resource)
when { context.workspace has classification && context.workspace.classification == "confidential" };

@id("classification:confidential:model-aliases")
forbid (principal, action == Action::"call_model", resource)
when { context.workspace has classification && context.workspace.classification == "confidential" };

@id("classification:confidential:reranker-forbidden")
forbid (principal, action == Action::"use_reranker", resource)
when { context.workspace has classification && context.workspace.classification == "confidential" };

@id("classification:confidential:log-masking-not-available")
forbid (principal, action in [Action::"call_tool", Action::"read_connector", Action::"write_connector"], resource)
when { context.workspace has classification && context.workspace.classification == "confidential" && context.reads_logs };

// == classification restricted ==
@id("classification:restricted:seat-not-allowed")
forbid (principal, action == Action::"use_seat", resource)
when { context.workspace has classification && context.workspace.classification == "restricted" };

// == classification secret ==
@id("classification:secret:seat-not-allowed")
forbid (principal, action == Action::"use_seat", resource)
when { context.workspace has classification && context.workspace.classification == "secret" };

// == workspace ws-a ==
@id("workspace:ws-a:device-profile-not-allowed")
forbid (principal, action == Action::"run_on_device", resource)
when { context.workspace == Workspace::"ws-a" && !["governed", "seat"].contains(context.profile) };

// client deny 3 kept by the client only: WebFetch(domain:example.com)
// client ask 1 (a client prompt, not a Cedar decision): Bash(git push:*)
@id("workspace:ws-a:tool-rule:kubectl-requires-context")
forbid (principal, action == Action::"run_command", resource)
when { context.workspace == Workspace::"ws-a" && context.point == "gateway" && resource.prefixes.contains("kubectl") && !resource.arguments.contains("--context") };

@id("workspace:ws-a:tool-rule:no-push-to-main")
forbid (principal, action == Action::"run_command", resource)
when { context.workspace == Workspace::"ws-a" && context.point == "gateway" && resource.prefixes.contains("git push origin main") };

@id("workspace:ws-a:tool-rule:no-push-to-master")
forbid (principal, action == Action::"run_command", resource)
when { context.workspace == Workspace::"ws-a" && context.point == "gateway" && resource.prefixes.contains("git push origin master") };

@id("workspace:ws-a:tool-rule:no-force-push")
forbid (principal, action == Action::"run_command", resource)
when { context.workspace == Workspace::"ws-a" && context.point == "gateway" && resource.prefixes.contains("git push") && resource.arguments.contains("--force") };

@id("workspace:ws-a:tool-rule:no-force-push-short")
forbid (principal, action == Action::"run_command", resource)
when { context.workspace == Workspace::"ws-a" && context.point == "gateway" && resource.prefixes.contains("git push") && resource.arguments.contains("-f") };

@id("workspace:ws-a:tool-rule:no-env-files")
forbid (principal, action in [Action::"read_path", Action::"write_path"], resource)
when { context.workspace == Workspace::"ws-a" && context.point == "gateway" && ["Edit", "MultiEdit", "Read", "Write"].contains(context.tool) && resource.path like "**/.env" };

@id("workspace:ws-a:tool-rule:no-aws-credentials")
forbid (principal, action in [Action::"read_path", Action::"write_path"], resource)
when { context.workspace == Workspace::"ws-a" && context.point == "gateway" && ["Edit", "MultiEdit", "Read", "Write"].contains(context.tool) && resource.path like "**/.aws/**" };

@id("workspace:ws-a:tool-rule:no-aws-credentials-home")
forbid (principal, action in [Action::"read_path", Action::"write_path"], resource)
when { context.workspace == Workspace::"ws-a" && context.point == "gateway" && ["Edit", "MultiEdit", "Read", "Write"].contains(context.tool) && resource.path like "~/.aws/**" };

@id("workspace:ws-a:command-unparseable")
forbid (principal, action == Action::"run_command", resource)
when { context.workspace == Workspace::"ws-a" && context.point == "gateway" && !resource.parseable };

@id("workspace:ws-a:client-deny:1")
@client_permission("Bash(kubectl delete:*)")
@translation("approximate")
forbid (principal, action == Action::"run_command", resource)
when { context.workspace == Workspace::"ws-a" && context.point == "client" && resource.prefixes.contains("kubectl delete") };

@id("workspace:ws-a:client-deny:2")
@client_permission("Read(./secrets/**)")
@translation("approximate")
forbid (principal, action in [Action::"read_path", Action::"write_path"], resource)
when { context.workspace == Workspace::"ws-a" && context.point == "client" && context.tool == "Read" && resource.path like "./secrets/**" };

// == workspace ws-b ==
@id("workspace:ws-b:model-allow-all")
permit (principal, action == Action::"call_model", resource)
when { context.workspace == Workspace::"ws-b" };

@id("workspace:ws-b:device-runs-disabled")
forbid (principal, action == Action::"run_on_device", resource)
when { context.workspace == Workspace::"ws-b" };

// agent_gateway_policy is invalid: no gateway rules (the gateway refuses)