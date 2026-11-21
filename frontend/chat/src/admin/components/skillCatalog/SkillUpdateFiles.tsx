import { useEffect, useState } from "react";

import { loadFile } from "./skillCatalogApi";
import { refusalText } from "./skillCatalogModel";
import type { MergeReport, SkillVersion } from "./skillCatalogTypes";
import { SkillMarkdown } from "./SkillMarkdown";
import { fileStatus, previewPaths } from "./skillUpdateModel";

// The side column of the update review (mock `renderUpdate` aside): the merge status per file with its local
// and upstream hunk counts, rendered previews of the merged SKILL.md and of files upstream added, and what happens
// on submit. Previews reload whenever the draft digest changes (a saved resolution rewrites the merged files).
export function SkillUpdateFiles({ skillId, draft, report, publishedVersion }: {
  skillId: string;
  draft: SkillVersion;
  report: MergeReport;
  publishedVersion: number | null;
}) {
  const paths = previewPaths(report, draft.files.map((file) => file.path));
  const pathKey = paths.join("\n");
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const wanted = pathKey ? pathKey.split("\n") : [];
    Promise.all(wanted.map((path) => loadFile(skillId, draft.version, path)))
      .then((rows) => {
        if (!alive) return;
        setTexts(Object.fromEntries(rows.map((row, index) => [wanted[index], String((row as { content?: unknown }).content ?? "")])));
        setProblem(null);
      })
      .catch((error) => { if (alive) setProblem(refusalText(error)); });
    return () => { alive = false; };
  }, [skillId, draft.version, draft.digest, pathKey]);

  return (
    <aside className="admin-panel__stack" data-testid="skill-update-files">
      <section className="work-detail__section">
        <h3>Files in draft v{draft.version}</h3>
        <div className="skills__files">
          {report.files.map((file) => {
            const status = fileStatus(file.status);
            return (
              <div key={file.path} className="skills__file" data-testid={`skill-update-file-${file.path}`}>
                {file.path}
                <span className="skills__file-meta">
                  <span className={`work-badge work-badge--${status.tone}`}>{status.label}</span>
                  {file.local_hunks ? <> <span className="work-badge work-badge--active">{file.local_hunks} local</span></> : null}
                  {file.upstream_hunks ? <> <span className="work-badge work-badge--running">{file.upstream_hunks} upstream</span></> : null}
                </span>
              </div>
            );
          })}
        </div>
      </section>
      {problem ? <p className="workspace-classification__message" role="alert">{problem}</p> : null}
      {paths.map((path) => (
        <section key={path} className="work-detail__section">
          <h3>Draft v{draft.version} preview · {path}</h3>
          {path in texts ? <SkillMarkdown text={texts[path]} maxHeight={path === "SKILL.md" ? "18rem" : "14rem"} testId={`skill-update-preview-${path}`} />
            : <p className="skills__hint" role="status">Loading…</p>}
        </section>
      ))}
      <section className="work-detail__section">
        <h3>What happens next</h3>
        <p className="skills__hint">
          Submitting freezes draft v{draft.version} and asks a second platform admin to approve it.
          {publishedVersion ? ` v${publishedVersion} stays live until v${draft.version} is published.` : " Nothing is delivered until it is published."}
          {report.path_moved ? " Publishing moves the tracked upstream path." : ""}
        </p>
      </section>
    </aside>
  );
}
