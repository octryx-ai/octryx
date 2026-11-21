// The code changes of a mobile chat's Mac jobs, one expandable diff per change.

import { codeChanges } from "./mobileFilesArtifacts";

export function JobCodeChanges({ changes }: { changes: ReturnType<typeof codeChanges> }) {
  return (
    <section className="m-changes" aria-label="Code changes">
      <span className="m-eyebrow">Code changes · {changes.length}</span>
      {changes.map((change) => (
        <details key={change.key}>
          <summary>
            {change.tool} · {change.file}
          </summary>
          <pre>{change.diff || "No diff sent for this change."}</pre>
        </details>
      ))}
    </section>
  );
}
