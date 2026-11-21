import { publishProveStatus, type PublishProve } from "./publishProveView";

export function PublishProveStatus({ value }: { value?: PublishProve | null }) {
  const lines = publishProveStatus(value);
  if (!lines.length) return null;
  return <section aria-label="Publication and functional acceptance" data-testid="publish-prove-status">
    {lines.map(line => <div className="resume-notice__body" key={line}>{line}</div>)}
  </section>;
}
