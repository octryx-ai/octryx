import { REST_REQUEST_NOTE, restRequestLines, type RestRequestView } from "./restRequestView";
import { RedactedText } from "../redaction/RedactedText";

// The request a custom REST write would send (backend), inside the central approval's preview: the request in
// one line, the connection, the body as fields (masked by the server), where it goes and the scope Octryx sets. The
// layout reuses the approval preview and the write plan's field list.
export function RestRequestPreview({ view }: { view: RestRequestView }) {
  const lines = restRequestLines(view);
  return (
    <section className="approval-preview" data-testid="rest-request-preview" aria-label="Request to send">
      <div className="approval-preview__header">
        <div className="approval-preview__title">{view.title}</div>
        {view.connection ? <div className="approval-preview__summary">via {view.connection}</div> : null}
      </div>
      {view.fields.length ? (
        <dl className="write-plan__fields" aria-label="Body">
          {view.fields.map((field) => (
            <div key={field.key} className="write-plan__field">
              <dt>{field.label}</dt>
              <dd><RedactedText value={field.value} /></dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="write-plan__muted">The request has no body.</p>
      )}
      {lines.length ? (
        <ul className="approval-preview__list">
          {lines.map((line) => (
            <li key={line}><RedactedText value={line} /></li>
          ))}
        </ul>
      ) : null}
      {view.bodyJson ? (
        <details className="approval-preview__details">
          <summary>Body as JSON</summary>
          <pre className="approval-preview__code"><RedactedText value={view.bodyJson} /></pre>
        </details>
      ) : null}
      <p className="write-plan__muted">{REST_REQUEST_NOTE}</p>
    </section>
  );
}
