import type { GitRequest, ImportMode } from "./skillImportModel";

// The first step of a Git or marketplace import (mock `renderImport` git / market step 0): where to read
// from. Inspect reads the repository once, read-only; nothing is imported yet.
export function SkillImportGit({ mode, request, onChange }: {
  mode: Exclude<ImportMode, "upload">;
  request: GitRequest;
  onChange: (change: Partial<GitRequest>) => void;
}) {
  const market = mode === "market";
  return (
    <>
      <label className="admin-panel__field">
        <span>{market ? "Marketplace repository" : "Repository URL"}</span>
        <input className="skills__mono" value={request.url} placeholder="https://…" data-testid="skill-import-url"
          onChange={(event) => onChange({ url: event.target.value })} />
      </label>
      <div className="admin-panel__form-grid">
        <label className="admin-panel__field">
          <span>Branch or tag</span>
          <input className="skills__mono" value={request.ref} placeholder="Empty: the default branch" data-testid="skill-import-ref"
            onChange={(event) => onChange({ ref: event.target.value })} />
        </label>
        {market ? (
          <label className="admin-panel__field">
            <span>Plugin name</span>
            <input className="skills__mono" value={request.marketplacePlugin} placeholder="Entry name in marketplace.json"
              data-testid="skill-import-plugin" onChange={(event) => onChange({ marketplacePlugin: event.target.value })} />
          </label>
        ) : (
          <label className="admin-panel__field">
            <span>Path (optional)</span>
            <input className="skills__mono" value={request.path} placeholder="Folder inside the repository" data-testid="skill-import-path"
              onChange={(event) => onChange({ path: event.target.value })} />
          </label>
        )}
      </div>
      {market ? (
        <p className="skills__hint">Reads <span className="skills__mono">.claude-plugin/marketplace.json</span>, resolves the entry&apos;s{" "}
          <span className="skills__mono">source</span> (a folder in the same repository, or a Git source pinned by commit) and lists
          the plugin&apos;s components. Nothing is imported yet.</p>
      ) : (
        <p className="skills__hint">Inspect reads the repository once (read-only). It finds every folder with a SKILL.md, plugin MCP
          servers, the licence and the commit. Nothing is imported yet. The host must be on the allowed-hosts list.</p>
      )}
    </>
  );
}
