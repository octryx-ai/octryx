import type { CodingSessionDetailData, CodingSessionSummary } from "./codingTypes";
import { recordValue } from "./codingSessionValues";
import { CodingWorkspaceEvidence } from "./CodingWorkspaceEvidence";
import { TimeText } from "../../admin/utils/TimeText";
import { CompactJson, KeyValue } from "./codingDetailParts";
import { arrayValue, contextBudgetRecord, stringValue, workspaceRecords } from "./codingDetailValues";

// The agent run's record: the task chat, the governed pipeline's stage trace, the secure execution scope and the
// model-visible context budget. Live output of the Changes step and part of the session's Details.
export function TaskChatSummary({ session }: { session: CodingSessionSummary }) {
  const latest = session.latestAgentSession;
  if (!latest) {
    return null;
  }
  return (
    <section className="coding-task-chat">
      <div>
        <div className="work-area__eyebrow">Task chat</div>
        <h3>{latest.restart ? "Fresh restart session" : "Agent communication session"}</h3>
        <p>
          Use this chat to communicate with the coding agent for {session.sourceKey}. Previous sessions remain
          audit evidence when a run is declined or restarted.
        </p>
      </div>
      <div className="coding-task-chat__meta">
        <span>{latest.status || "unknown"}</span>
        <span>{latest.run_status || "run status pending"}</span>
        <TimeText value={latest.started_at} fallback="no timestamp" />
      </div>
      {/* Neutral: the header carries the session's one primary action. */}
      <a className="work-area__button" href={latest.chat_url}>
        Open task chat
      </a>
    </section>
  );
}

export function CodingProcessTrace({ detail }: { detail: CodingSessionDetailData | null }) {
  const trace = detail?.pipelineTrace;
  const stages = trace?.run?.stages || trace?.stages || [];
  const executionContext = recordValue(trace?.run?.summary?.execution_context);
  const workspaces = workspaceRecords(detail);
  const contextBudget = contextBudgetRecord(detail);
  if (!trace?.run) {
    return (
      <div className="work-empty">
        <div className="work-empty__eyebrow">No pipeline run</div>
        <h2>No Coding Pipeline run is attached to this session.</h2>
        <p>Start a governed coding pipeline from the Work Item or API before implementation begins.</p>
      </div>
    );
  }
  return (
    <div className="coding-detail__stack">
      <div className="coding-detail__metrics">
        <KeyValue label="Run status" value={trace.run.status} />
        <KeyValue label="Control" value={trace.run.control_state} />
        <KeyValue label="Current stage" value={trace.run.current_stage_key || "Complete"} />
        <KeyValue label="Stages" value={String(stages.length)} />
      </div>
      <CodingWorkspaceEvidence workspaces={workspaces} />
      {contextBudget ? <CodingContextBudgetEvidence budget={contextBudget} /> : null}
      {executionContext ? <SecureExecutionScope context={executionContext} /> : null}
      <section className="coding-detail__evidence">
        <h3>Stage trace</h3>
        <ol className="coding-process">
          {stages.map((stage) => (
            <li key={stage.id} className={`coding-process__stage is-${stage.status}`}>
              <div>
                <strong>{stage.label}</strong>
                <small>
                  {stage.stage_key} · {stage.required ? "required" : "optional"}
                </small>
              </div>
              <span className="work-badge">{stage.status}</span>
              {stage.required_actions.length > 0 ? (
                <p className="coding-detail__warning">{stage.required_actions.join(" ")}</p>
              ) : null}
              {stage.evidence.length > 0 || Object.keys(stage.outputs || {}).length > 0 ? (
                <CompactJson value={{ evidence: stage.evidence, outputs: stage.outputs, policy_refs: stage.policy_refs }} />
              ) : null}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

export function SecureExecutionScope({ context }: { context: Record<string, unknown> }) {
  const blockers = arrayValue(context.blockers);
  const repositories = arrayValue(context.repositories);
  const validationCommands = arrayValue(context.validation_commands);
  const safety = recordValue(context.workspace_safety);
  return (
    <section className="coding-detail__evidence">
      <h3>Secure execution scope</h3>
      <div className="coding-detail__metrics">
        <KeyValue label="Runtime" value={stringValue(context.runtime) || "local"} />
        <KeyValue label="Change Plan" value={stringValue(context.change_plan_id) || "Not approved"} />
        <KeyValue label="Change Units" value={arrayValue(context.change_unit_ids).length.toString()} />
        <KeyValue label="Blockers" value={blockers.length.toString()} />
      </div>
      {blockers.length > 0 ? (
        <ul>
          {blockers.map((blocker, index) => (
            <li key={`blocker-${index}`}>
              <CompactJson value={blocker} />
            </li>
          ))}
        </ul>
      ) : null}
      <CompactJson
        value={{
          repositories,
          validation_commands: validationCommands,
          workspace_safety: safety,
        }}
      />
    </section>
  );
}

export function CodingContextBudgetEvidence({ budget }: { budget: Record<string, unknown> }) {
  const fragments = recordValue(budget.fragments);
  const fragmentRows = Object.entries(fragments || {})
    .map(([key, value]) => ({ key, record: recordValue(value) }))
    .filter((entry): entry is { key: string; record: Record<string, unknown> } => Boolean(entry.record));
  const truncated = fragmentRows.filter((entry) => Boolean(entry.record.truncated));
  return (
    <section className="coding-context-budget">
      <div>
        <div className="work-area__eyebrow">Context budget</div>
        <h3>Model-visible prompt</h3>
      </div>
      <div className="coding-context-budget__metrics">
        <KeyValue label="Prompt chars" value={String(budget.total_prompt_chars ?? "-")} />
        <KeyValue label="Original chars" value={String(budget.total_original_chars ?? "-")} />
        <KeyValue label="Est. tokens" value={String(budget.estimated_prompt_tokens ?? "-")} />
        <KeyValue label="Truncated" value={String(truncated.length)} />
      </div>
      {fragmentRows.length ? (
        <div className="coding-context-budget__fragments">
          {fragmentRows.map(({ key, record }) => (
            <span key={key} className={`work-badge ${record.truncated ? "work-badge--attention" : ""}`}>
              {key}: {String(record.prompt_chars ?? "-")}/{String(record.original_chars ?? "-")}
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
}
