// Octryx baseline policy set - generated, do not edit. Schema 2026-10-08.2.
// Classification matrix: default. Workspaces: 1.

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
// == classification internal ==
// == classification confidential ==
@id("classification:confidential:seat-not-allowed")
forbid (principal, action == Action::"use_seat", resource)
when { context.workspace has classification && context.workspace.classification == "confidential" };

// == classification restricted ==
@id("classification:restricted:seat-not-allowed")
forbid (principal, action == Action::"use_seat", resource)
when { context.workspace has classification && context.workspace.classification == "restricted" };

// == classification secret ==
@id("classification:secret:seat-not-allowed")
forbid (principal, action == Action::"use_seat", resource)
when { context.workspace has classification && context.workspace.classification == "secret" };

// == workspace 11111111-2222-3333-4444-555555555555 ==
@id("workspace:11111111-2222-3333-4444-555555555555:model-denied")
forbid (principal, action == Action::"call_model", resource)
when { context.workspace == Workspace::"11111111-2222-3333-4444-555555555555" && ["octryx-legacy"].contains(resource.alias) };

@id("workspace:11111111-2222-3333-4444-555555555555:model-granted")
permit (principal, action == Action::"call_model", resource)
when { context.workspace == Workspace::"11111111-2222-3333-4444-555555555555" && ["octryx-opus", "octryx-sonnet"].contains(resource.alias) };

@id("workspace:11111111-2222-3333-4444-555555555555:device-profile-not-allowed")
forbid (principal, action == Action::"run_on_device", resource)
when { context.workspace == Workspace::"11111111-2222-3333-4444-555555555555" && !["governed", "seat"].contains(context.profile) };

@id("workspace:11111111-2222-3333-4444-555555555555:tool-rule:kubectl-requires-context")
forbid (principal, action == Action::"run_command", resource)
when { context.workspace == Workspace::"11111111-2222-3333-4444-555555555555" && context.point == "gateway" && resource.prefixes.contains("kubectl") && !resource.arguments.contains("--context") };

@id("workspace:11111111-2222-3333-4444-555555555555:tool-rule:no-push-to-main")
forbid (principal, action == Action::"run_command", resource)
when { context.workspace == Workspace::"11111111-2222-3333-4444-555555555555" && context.point == "gateway" && resource.prefixes.contains("git push origin main") };

@id("workspace:11111111-2222-3333-4444-555555555555:tool-rule:no-push-to-master")
forbid (principal, action == Action::"run_command", resource)
when { context.workspace == Workspace::"11111111-2222-3333-4444-555555555555" && context.point == "gateway" && resource.prefixes.contains("git push origin master") };

@id("workspace:11111111-2222-3333-4444-555555555555:tool-rule:no-force-push")
forbid (principal, action == Action::"run_command", resource)
when { context.workspace == Workspace::"11111111-2222-3333-4444-555555555555" && context.point == "gateway" && resource.prefixes.contains("git push") && resource.arguments.contains("--force") };

@id("workspace:11111111-2222-3333-4444-555555555555:tool-rule:no-force-push-short")
forbid (principal, action == Action::"run_command", resource)
when { context.workspace == Workspace::"11111111-2222-3333-4444-555555555555" && context.point == "gateway" && resource.prefixes.contains("git push") && resource.arguments.contains("-f") };

@id("workspace:11111111-2222-3333-4444-555555555555:tool-rule:no-env-files")
forbid (principal, action in [Action::"read_path", Action::"write_path"], resource)
when { context.workspace == Workspace::"11111111-2222-3333-4444-555555555555" && context.point == "gateway" && ["Edit", "MultiEdit", "Read", "Write"].contains(context.tool) && resource.path like "**/.env" };

@id("workspace:11111111-2222-3333-4444-555555555555:tool-rule:no-aws-credentials")
forbid (principal, action in [Action::"read_path", Action::"write_path"], resource)
when { context.workspace == Workspace::"11111111-2222-3333-4444-555555555555" && context.point == "gateway" && ["Edit", "MultiEdit", "Read", "Write"].contains(context.tool) && resource.path like "**/.aws/**" };

@id("workspace:11111111-2222-3333-4444-555555555555:tool-rule:no-aws-credentials-home")
forbid (principal, action in [Action::"read_path", Action::"write_path"], resource)
when { context.workspace == Workspace::"11111111-2222-3333-4444-555555555555" && context.point == "gateway" && ["Edit", "MultiEdit", "Read", "Write"].contains(context.tool) && resource.path like "~/.aws/**" };

@id("workspace:11111111-2222-3333-4444-555555555555:command-unparseable")
forbid (principal, action == Action::"run_command", resource)
when { context.workspace == Workspace::"11111111-2222-3333-4444-555555555555" && context.point == "gateway" && !resource.parseable };

@id("workspace:11111111-2222-3333-4444-555555555555:client-deny:1")
@client_permission("Bash(git push origin main:*)")
@translation("approximate")
forbid (principal, action == Action::"run_command", resource)
when { context.workspace == Workspace::"11111111-2222-3333-4444-555555555555" && context.point == "client" && resource.prefixes.contains("git push origin main") };

@id("workspace:11111111-2222-3333-4444-555555555555:client-deny:2")
@client_permission("Bash(git push origin master:*)")
@translation("approximate")
forbid (principal, action == Action::"run_command", resource)
when { context.workspace == Workspace::"11111111-2222-3333-4444-555555555555" && context.point == "client" && resource.prefixes.contains("git push origin master") };

@id("workspace:11111111-2222-3333-4444-555555555555:client-deny:3")
@client_permission("Bash(git push --force:*)")
@translation("approximate")
forbid (principal, action == Action::"run_command", resource)
when { context.workspace == Workspace::"11111111-2222-3333-4444-555555555555" && context.point == "client" && resource.prefixes.contains("git push --force") };

@id("workspace:11111111-2222-3333-4444-555555555555:client-deny:4")
@client_permission("Read(./.env)")
@translation("approximate")
forbid (principal, action in [Action::"read_path", Action::"write_path"], resource)
when { context.workspace == Workspace::"11111111-2222-3333-4444-555555555555" && context.point == "client" && context.tool == "Read" && resource.path like "./.env" };

@id("workspace:11111111-2222-3333-4444-555555555555:client-deny:5")
@client_permission("Read(~/.aws/**)")
@translation("approximate")
forbid (principal, action in [Action::"read_path", Action::"write_path"], resource)
when { context.workspace == Workspace::"11111111-2222-3333-4444-555555555555" && context.point == "client" && context.tool == "Read" && resource.path like "~/.aws/**" };
