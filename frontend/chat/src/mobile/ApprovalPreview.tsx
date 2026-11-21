// The approval preview at phone width: REST request, write plan, connector write or a generic command.
import { REST_REQUEST_NOTE, restRequestLines, restRequestView } from "../chat/approval/restRequestView";
import { connectorWriteView } from "../chat/approval/connectorWriteView";
import { writePlanView } from "../chat/approval/writePlanView";
import { RedactedText } from "../chat/redaction/RedactedText";
import { bodyRows, foldedSize, type PhoneApproval } from "./phoneApprovals";
import { PlanScope, Writes } from "./WritePlanApprovalCard";

function Rows({ fields, label }: { fields: Array<{ key: string; label: string; value: string }>; label: string }) {
  if (!fields.length) return <p className="m-muted">The request has no body.</p>;
  return (
    <dl className="m-write-fields" aria-label={label}>
      {bodyRows(fields).map((row, index) => (
        <div key={`${row.key}-${index}`}>
          <dt>{row.label}</dt>
          <dd>
            {row.json ? (
              <details className="m-approval-fold">
                <summary>{foldedSize(row.json)}</summary>
                <pre className="m-plan-pre"><RedactedText value={row.json} /></pre>
              </details>
            ) : (
              <RedactedText value={row.value} />
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Lines({ lines }: { lines: string[] }) {
  return lines.length ? (
    <ul className="m-plan-lines">
      {lines.map((line, index) => (
        <li key={`${line}-${index}`}><RedactedText value={line} /></li>
      ))}
    </ul>
  ) : null;
}

/** The preview at phone width, from the same models the web's approval page uses. */
export function PhonePreview({ approval }: { approval: PhoneApproval }) {
  const payload = approval.payload;
  if (approval.preview === "rest") {
    const view = restRequestView(payload);
    if (!view) return null;
    return (
      <div className="m-approval-preview" data-testid="m-approval-rest">
        {view.connection && <p className="m-muted">via {view.connection}</p>}
        <Rows fields={view.fields} label="Body" />
        <Lines lines={restRequestLines(view)} />
        <p className="m-muted m-approval-note">{REST_REQUEST_NOTE}</p>
      </div>
    );
  }
  if (approval.preview === "plan") {
    const plan = writePlanView(payload);
    if (!plan) return null;
    return (
      <div className="m-approval-preview m-plan">
        {plan.request && <p className="m-plan-request"><RedactedText value={plan.request} /></p>}
        <PlanScope scope={plan.scope} />
        <Writes writes={plan.writes} startOpen={!plan.many} />
      </div>
    );
  }
  if (approval.preview === "connector") {
    const view = connectorWriteView(payload, typeof payload?.toolName === "string" ? payload.toolName : null);
    if (!view) return null;
    return (
      <div className="m-approval-preview">
        {view.connector && <p className="m-muted">Writes to {view.connector}</p>}
        <Rows fields={view.fields} label="Fields to write" />
      </div>
    );
  }
  if (approval.preview === "generic" && payload) {
    const str = (value: unknown) => (typeof value === "string" ? value : "");
    const details = approval.details ?? (Array.isArray(payload.details) ? payload.details.map(String).filter(Boolean) : []);
    // A local command's gate names the command in its standing rule's argument class ("git status").
    const rule = payload.standing_rule && typeof payload.standing_rule === "object" ? (payload.standing_rule as Record<string, unknown>) : null;
    const command = str(payload.command) || str(rule?.argument_class);
    return (
      <div className="m-approval-preview">
        {str(payload.summary) && <p><RedactedText value={str(payload.summary)} /></p>}
        {command && <pre className="m-plan-pre"><RedactedText value={command} /></pre>}
        <Lines lines={details} />
      </div>
    );
  }
  return approval.action ? <p className="m-muted"><RedactedText value={approval.action} /></p> : null;
}
