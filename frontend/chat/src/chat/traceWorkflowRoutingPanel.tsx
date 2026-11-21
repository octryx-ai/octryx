import type { TurnTrace } from "../chatThreadTypes";
import { TraceValue } from "./traceUiComponents";

export type RoutingResolution = {
  source?: string | null;
  status?: string | null;
  fallback_reason?: string | null;
  workflow_id?: string | null;
  workflow_class?: string | null;
  policy_id?: string | null;
  policy_version_id?: string | null;
  matched_group_id?: string | null;
  tool_policy?: {
    allowlist?: unknown[];
    denylist?: unknown[];
  } | null;
  safety_constraints?: Record<string, unknown> | null;
};

export type WorkflowContract = {
  workflow_id?: string | null;
  workflow_class?: string | null;
  workflow_contract_source?: string | null;
  workflow_routing_policy_id?: string | null;
  workflow_routing_policy_version_id?: string | null;
  workflow_routing_policy_matched_group_id?: string | null;
  diagram_source?: string | null;
  diagram_detail?: string | null;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;
}

function routingResolutionFromTrace(trace: TurnTrace): RoutingResolution | null {
  const snapshot = asRecord(trace.contextSnapshot);
  const requestAnalysis = asRecord(snapshot?.request_analysis);
  const resolution = asRecord(
    requestAnalysis?.workflow_routing_policy_resolution,
  );
  return resolution ? (resolution as RoutingResolution) : null;
}

function workflowContractFromTrace(trace: TurnTrace): WorkflowContract | null {
  const snapshot = asRecord(trace.contextSnapshot);
  const requestAnalysis = asRecord(snapshot?.request_analysis);
  const contract = asRecord(requestAnalysis?.workflow_contract);
  return contract ? (contract as WorkflowContract) : null;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => String(item || "").trim()).filter(Boolean);
}

function routingStatusClassName({
  isDbContract,
  isDbMatch,
}: {
  isDbContract: boolean;
  isDbMatch: boolean;
}) {
  if (isDbContract || isDbMatch) {
    return "trace-routing__badge trace-routing__badge--matched";
  }
  return "trace-routing__badge";
}

function RoutingGrid({
  resolution,
  workflowContract,
  contractSource,
  source,
}: {
  resolution: RoutingResolution | null;
  workflowContract: WorkflowContract | null;
  contractSource: string;
  source: string;
}) {
  const workflowClass = workflowContract?.workflow_class || resolution?.workflow_class;
  const policyVersion = workflowContract?.workflow_routing_policy_version_id || resolution?.policy_version_id;
  return (
    <dl className="trace-routing__grid">
      <div>
        <dt>Workflow</dt>
        <dd>
          {workflowContract?.workflow_id || resolution?.workflow_id || "-"}
          {workflowClass ? <span>{workflowClass}</span> : null}
        </dd>
      </div>
      <div>
        <dt>Contract source</dt>
        <dd>{contractSource}</dd>
      </div>
      <div>
        <dt>Diagram source</dt>
        <dd>
          {workflowContract?.diagram_source || "-"}
          {workflowContract?.diagram_detail ? (
            <span>{workflowContract.diagram_detail}</span>
          ) : null}
        </dd>
      </div>
      <div>
        <dt>Policy</dt>
        <dd>
          {workflowContract?.workflow_routing_policy_id || resolution?.policy_id || "-"}
          {policyVersion ? <span>{policyVersion}</span> : null}
        </dd>
      </div>
      <div>
        <dt>Matched group</dt>
        <dd>
          {workflowContract?.workflow_routing_policy_matched_group_id || resolution?.matched_group_id || "-"}
        </dd>
      </div>
      <div>
        <dt>Source</dt>
        <dd>{source}</dd>
      </div>
    </dl>
  );
}

function ToolList({ label, tools }: { label: string; tools: string[] }) {
  return (
    <div className="trace-routing__tools">
      <span>{label}</span>
      <div>
        {tools.map((tool) => (
          <span key={tool}>{tool}</span>
        ))}
      </div>
    </div>
  );
}

function RoutingHeader({
  resolution,
  isDbContract,
  isDbMatch,
}: {
  resolution: RoutingResolution | null;
  isDbContract: boolean;
  isDbMatch: boolean;
}) {
  return (
    <div className="trace-routing__header">
      <div>
        <h4>Workflow Routing</h4>
        <div className="trace-routing__copy">
          {isDbContract
            ? "The effective workflow contract was sourced from database routing."
            : isDbMatch
              ? "A database-managed routing policy matched; the workflow contract used code fallback or enrichment."
              : resolution?.fallback_reason || "Code routing fallback was used."}
        </div>
      </div>
      <span
        className={routingStatusClassName({ isDbContract, isDbMatch })}
      >
        {isDbContract ? "DB contract" : isDbMatch ? "DB matched" : "Fallback"}
      </span>
    </div>
  );
}

export function TraceWorkflowRoutingPanel({
  trace,
  resolution: explicitResolution,
  workflowContract: explicitWorkflowContract,
}: {
  trace?: TurnTrace;
  resolution?: RoutingResolution | Record<string, unknown> | null;
  workflowContract?: WorkflowContract | Record<string, unknown> | null;
}) {
  const resolution = explicitResolution
    ? (explicitResolution as RoutingResolution)
    : trace
      ? routingResolutionFromTrace(trace)
      : null;
  const workflowContract = explicitWorkflowContract
    ? (explicitWorkflowContract as WorkflowContract)
    : trace
      ? workflowContractFromTrace(trace)
      : null;
  if (!resolution && !workflowContract) {
    return null;
  }
  const source = String(resolution?.source || "unknown");
  const status = String(resolution?.status || "unknown");
  const contractSource = String(
    workflowContract?.workflow_contract_source || "code_fallback",
  );
  const allowlist = stringList(resolution?.tool_policy?.allowlist);
  const denylist = stringList(resolution?.tool_policy?.denylist);
  const safetyConstraints = asRecord(resolution?.safety_constraints);
  const isDbMatch = source === "db" && status === "matched";
  const isDbContract = contractSource === "db_routing_policy";

  return (
    <section className="turn-trace-section trace-routing">
      <RoutingHeader resolution={resolution} isDbContract={isDbContract} isDbMatch={isDbMatch} />

      <RoutingGrid resolution={resolution} workflowContract={workflowContract} contractSource={contractSource} source={source} />

      {allowlist.length ? <ToolList label="Allowed tools" tools={allowlist} /> : null}

      {denylist.length ? <ToolList label="Denied tools" tools={denylist} /> : null}

      {safetyConstraints ? (
        <details className="trace-routing__details">
          <summary>Safety constraints</summary>
          <TraceValue value={safetyConstraints} />
        </details>
      ) : null}
    </section>
  );
}
