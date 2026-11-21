import type { ReactNode } from "react";

import type { WorkItem, WorkItemLifecycle } from "./workItemTypes";
import { asArray, isHttpUrl, isRecord, stringifyValue } from "./workItemDetailValues";
import { automationModeText, automationPolicySourceText, automationReasonsText } from "./workAutomationText";

// The detail's read-only blocks: lifecycle, automation, external activity, source mapping and the shared section /
// key-value markup.

export function LifecycleSummary({ lifecycle, item }: { lifecycle: WorkItemLifecycle | null; item: WorkItem }) {
  if (!lifecycle) {
    return <p className="work-detail__empty">Loading lifecycle links...</p>;
  }
  const active = lifecycle.active_agent_session;
  return (
    <div className="work-detail__stack">
      <div className="work-detail__status-strip">
        <ExternalEvidenceLink href={lifecycle.links.jira_url} label="Jira" />
        <ExternalEvidenceLink href={lifecycle.links.coding_url} label="Coding cockpit" />
        <ExternalEvidenceLink href={active?.chat_url || lifecycle.links.active_chat_url} label="Task chat" />
        <span>{active ? `${active.status || "unknown"} · ${active.run_status || "run pending"}` : "No task chat yet"}</span>
      </div>
      <div className="work-detail__kv-grid">
        <DetailKeyValue label="Work item" value={item.source_key} />
        <DetailKeyValue label="Agent sessions" value={lifecycle.agent_sessions.length} />
        <DetailKeyValue label="Branches" value={lifecycle.branches.length} />
        <DetailKeyValue label="Pull requests" value={lifecycle.pull_requests.length} />
      </div>
      <LifecycleBranchList branches={lifecycle.branches} />
      <LifecycleAgentSessionList sessions={lifecycle.agent_sessions} />
    </div>
  );
}

function LifecycleBranchList({ branches }: { branches: WorkItemLifecycle["branches"] }) {
  if (branches.length === 0) {
    return <p className="work-detail__empty">No governed branch captured yet.</p>;
  }
  return (
    <ul className="work-detail__object-list">
      {branches.map((branch) => (
        <li key={branch.change_unit_id}>
          <strong>{branch.repository_name}</strong>
          <div>
            <ExternalEvidenceLink href={branch.branch_url} label={branch.branch_name || "No branch"} />
            {" · "}
            <ExternalEvidenceLink href={branch.pull_request_url} label={branch.pull_request_url ? "PR" : "No PR"} />
            {" · "}
            {branch.status}
          </div>
        </li>
      ))}
    </ul>
  );
}

function LifecycleAgentSessionList({ sessions }: { sessions: WorkItemLifecycle["agent_sessions"] }) {
  if (sessions.length === 0) {
    return <p className="work-detail__empty">No coding agent chat session captured yet.</p>;
  }
  return (
    <ul className="work-detail__object-list">
      {sessions.map((session) => (
        <li key={session.id}>
          <ExternalEvidenceLink href={session.chat_url} label={session.restart ? "Restarted task chat" : "Task chat"} />
          <div>
            {[session.status, session.run_status, session.started_at].filter(Boolean).join(" · ")}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function AutomationEligibility({ item }: { item: WorkItem }) {
  const eligibility = item.automation_eligibility;
  if (!eligibility) {
    return <p className="work-detail__empty">No automation eligibility was calculated for this Work Item.</p>;
  }
  return (
    <div className="work-detail__kv-grid">
      <DetailKeyValue label="Requested by label" value={eligibility.requested ? "Yes" : "No"} />
      <DetailKeyValue label="Can start" value={eligibility.can_start ? "Yes" : "No"} />
      <DetailKeyValue label="Mode" value={automationModeText(eligibility.mode)} />
      <DetailKeyValue label="Trigger labels" value={eligibility.trigger_labels} />
      <DetailKeyValue label="Matched labels" value={eligibility.matched_labels} />
      <DetailKeyValue label="Blocking reasons" value={automationReasonsText(eligibility.blocking_reasons)} />
      <DetailKeyValue label="Review reasons" value={automationReasonsText(eligibility.review_reasons)} />
      <DetailKeyValue label="Policy source" value={automationPolicySourceText(eligibility.policy_source)} />
    </div>
  );
}

export function DetailSection({ title, children, id }: { title: string; children: ReactNode; id?: string }) {
  return (
    <section className="work-detail__section" id={id}>
      <h3>{title}</h3>
      {children}
    </section>
  );
}

export function DetailKeyValue({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="work-detail__kv">
      <dt>{label}</dt>
      <dd>{stringifyValue(value)}</dd>
    </div>
  );
}

export function ObjectList({ values, emptyText }: { values: unknown[]; emptyText: string }) {
  if (values.length === 0) return <p className="work-detail__empty">{emptyText}</p>;
  return (
    <ul className="work-detail__object-list">
      {values.map((value, index) => (
        <li key={`${index}-${stringifyValue(value).slice(0, 40)}`}>{stringifyValue(value)}</li>
      ))}
    </ul>
  );
}

export function ExternalActivity({ values }: { values: unknown[] }) {
  if (values.length === 0) return <p className="work-detail__empty">No external watcher activity captured.</p>;
  return (
    <ul className="work-detail__object-list">
      {values.map((value, index) => {
        const record = isRecord(value) ? value : {};
        const issue = isRecord(record.issue) ? record.issue : {};
        const page = isRecord(record.page) ? record.page : {};
        const document = isRecord(record.document) ? record.document : {};
        const repository = isRecord(record.repository) ? record.repository : {};
        const ruleDecisions = asArray(record.rule_decisions);
        const resultingActions = asArray(record.resulting_actions);
        const title = [
          stringifyValue(record.event_type),
          stringifyValue(issue.key),
          stringifyValue(page.title || page.id),
          stringifyValue(document.key || document.title),
          stringifyValue(repository.slug || repository.name),
          stringifyValue(record.branch),
        ].filter((entry) => entry !== "-").join(" · ");
        return (
          <li key={`${index}-${title.slice(0, 40)}`}>
            <strong>{title || "External event"}</strong>
            <div>
              {[stringifyValue(record.source), stringifyValue(record.actor), stringifyValue(record.received_at)]
                .filter((entry) => entry !== "-")
                .join(" · ")}
            </div>
            <div>{record.requires_replan ? "Requires replan" : record.source_evidence_stale ? "Source evidence stale" : "Linked"}</div>
            <div>Linked session: {stringifyValue(record.event_id)}</div>
            {resultingActions.length > 0 ? <div>Actions: {resultingActions.map(stringifyValue).join(", ")}</div> : null}
            {ruleDecisions.length > 0 ? (
              <details className="work-detail__raw">
                <summary>Rule decisions</summary>
                <pre>{JSON.stringify(ruleDecisions, null, 2)}</pre>
              </details>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

export function MappingGrid({ groups }: { groups: Array<{ title: string; values: string[] }> }) {
  return (
    <div className="work-detail__mapping">
      {groups.map((group) => (
        <div key={group.title}>
          <h4>{group.title}</h4>
          <ul>
            {group.values.map((value) => (
              <li key={value}>{value}</li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

export function FutureData({ value }: { value: unknown }) {
  const values = asArray(value);
  if (values.length > 0) return <ObjectList values={values} emptyText="" />;
  if (isRecord(value) && Object.keys(value).length > 0) {
    return <pre className="work-detail__compact-json">{JSON.stringify(value, null, 2)}</pre>;
  }
  return <p className="work-detail__empty">Not captured yet.</p>;
}

export function ExternalEvidenceLink({ href, label }: { href?: string | null; label: string }) {
  if (!href || !isNavigableUrl(href)) {
    return <span>{label}</span>;
  }
  return (
    <a className="work-detail__external-link" href={href} target="_blank" rel="noreferrer">
      {label}
    </a>
  );
}


function isNavigableUrl(value: string): boolean {
  return isHttpUrl(value) || value.startsWith("/chat?");
}
