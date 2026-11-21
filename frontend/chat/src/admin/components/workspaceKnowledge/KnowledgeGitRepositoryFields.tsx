import type { FormState } from "./connectorFormModel";
import { MAX_FILE_BYTES, MAX_FILES, bytesText } from "./gitRepositoryScope";
import { KnowledgeFormField } from "./KnowledgeFormField";

const PAIR = { display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: "0.5rem" } as const;
const GLOBS = { minHeight: "4.5rem" } as const;
const GLOBS_CLASS = "admin-panel__textarea admin-panel__textarea--code";

// lockedUrl: a repository added "From a connection" (Bitbucket, with an access mode) keeps its URL.
// urlProblem: the server refused the address when asked for its connections (no known Git host).
type Props = { form: FormState; set: (patch: Partial<FormState>) => void; lockedUrl?: boolean; urlProblem?: string | null };

// Git repository: one public github.com repository, or a bitbucket.org repository read with the Workspace's
// Bitbucket Cloud connection, at a ref, narrowed by include/exclude globs and bounded by a file count and a per-file
// size. There is no credential field: the server resolves the connection.
// A repository added "From a connection" keeps its URL here (its access mode changes in the source's panel); which
// connection reads it is the Connection select under these fields (KnowledgeGitConnectionSelect).
export function KnowledgeGitRepositoryFields({ form, set, lockedUrl = false, urlProblem = null }: Props) {
  return (
    <>
      <div style={PAIR}>
        <KnowledgeFormField label="Repository URL">
          <input className="admin-panel__input" aria-label="Repository URL" value={form.repositoryUrl}
            placeholder="https://github.com/<owner>/<repo>" readOnly={lockedUrl}
            onChange={(event) => set({ repositoryUrl: event.target.value })} />
          {urlProblem ? <span className="admin-panel__hint" role="alert" data-testid="repository-url-problem">{urlProblem}</span> : null}
        </KnowledgeFormField>
        <KnowledgeFormField label="Ref (branch, tag or commit)">
          <input className="admin-panel__input" aria-label="Ref" value={form.ref}
            placeholder="Ref: branch, tag or 40-character commit sha"
            onChange={(event) => set({ ref: event.target.value })} />
        </KnowledgeFormField>
      </div>
      <div style={PAIR}>
        <KnowledgeFormField label="Include globs">
          <textarea className={GLOBS_CLASS} aria-label="Include globs" value={form.includeGlobs} style={GLOBS}
            spellCheck={false} placeholder={"Include globs (optional), one per line, e.g.\nsrc/**/*.java\ndocs/**/*.md"}
            onChange={(event) => set({ includeGlobs: event.target.value })} />
        </KnowledgeFormField>
        <KnowledgeFormField label="Exclude globs">
          <textarea className={GLOBS_CLASS} aria-label="Exclude globs" value={form.excludeGlobs} style={GLOBS}
            spellCheck={false} placeholder={"Exclude globs (optional), one per line, e.g.\n**/test/**"}
            onChange={(event) => set({ excludeGlobs: event.target.value })} />
        </KnowledgeFormField>
      </div>
      <div style={PAIR}>
        <KnowledgeFormField label="Max files">
          <input className="admin-panel__input" type="number" aria-label="Max files" value={form.maxFiles}
            min={MAX_FILES.min} max={MAX_FILES.max} title="Max files"
            placeholder={`Max files (default ${MAX_FILES.serverDefault})`}
            onChange={(event) => set({ maxFiles: event.target.value })} />
        </KnowledgeFormField>
        <KnowledgeFormField label="Max file size (bytes)">
          <input className="admin-panel__input" type="number" aria-label="Max file size in bytes" value={form.maxFileBytes}
            min={MAX_FILE_BYTES.min} max={MAX_FILE_BYTES.max} title="Max file size in bytes"
            placeholder={`Max file size in bytes (default ${MAX_FILE_BYTES.serverDefault} = ${bytesText(MAX_FILE_BYTES.serverDefault)})`}
            onChange={(event) => set({ maxFileBytes: event.target.value })} />
        </KnowledgeFormField>
      </div>
    </>
  );
}
