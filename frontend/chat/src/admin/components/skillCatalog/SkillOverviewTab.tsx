import { FileContent } from "./SkillFilesTab";
import { STATE_LABELS, formatSize } from "./skillCatalogModel";
import type { SkillVersion } from "./skillCatalogTypes";
import { useSkillFile } from "./useSkillFile";

const SKILL_FILE = "SKILL.md";
const MCP_FILE = ".mcp.json";

// Detail → Overview (mock `renderDetail` overview, `mcpOverview`): the rendered SKILL.md of the working version; for
// an MCP server entry the note that it is not a skill, its plugin files and the launch spec (verbatim → reviewed).
export function SkillOverviewTab({ skillId, kind, version }: { skillId: string; kind: string; version: SkillVersion }) {
  const mcp = kind === "mcp_server";
  const path = mcp ? (version.files.some((file) => file.path === MCP_FILE) ? MCP_FILE : null) : SKILL_FILE;
  const file = useSkillFile(skillId, version.version, path);
  const label = `${STATE_LABELS[version.state].toLowerCase()} v${version.version}`;
  if (!mcp) {
    return (
      <div data-testid="skill-overview">
        <FileContent path={SKILL_FILE} file={file} testId="skill-overview-md" />
        <p className="skills__hint">Rendered SKILL.md of the {label}.</p>
      </div>
    );
  }
  const spec = version.launch_spec ?? {};
  return (
    <div data-testid="skill-overview">
      <div className="policies__warn"><b>This entry is not a skill.</b> It comes from a plugin that brings an MCP server instead of a
        SKILL.md. The catalog keeps it as a reviewed <b>MCP server entry</b>; it only starts where the Workspace MCP policy allows it.</div>
      <div className="admin-panel__card skill-detail__gap">
        <div className="admin-panel__section-header">Plugin files</div>
        <div className="skills__scroll">
          <table className="admin-panel__table">
            <thead><tr><th scope="col">File</th><th scope="col">Kind</th><th scope="col">Size</th></tr></thead>
            <tbody>
              {version.files.map((entry) => (
                <tr key={entry.path}><td className="skills__mono">{entry.path}</td><td>{entry.kind}</td><td>{formatSize(entry.size)}</td></tr>
              ))}
              {version.files.length ? null : <tr><td colSpan={3}><div className="admin-panel__empty-state">No plugin files recorded.</div></td></tr>}
            </tbody>
          </table>
        </div>
      </div>
      <div className="admin-panel__card skill-detail__gap">
        <div className="admin-panel__section-header">Launch spec · upstream (verbatim) → reviewed</div>
        {path ? <FileContent path={path} file={file} testId="skill-overview-mcp-json" /> : <p className="skills__hint">No .mcp.json in this version.</p>}
        <pre className="policies__code skill-detail__gap" data-testid="skill-overview-launch-spec">{JSON.stringify(spec, null, 2)}</pre>
        <p className="skills__hint">
          {spec.image ? (spec.image_digest
            ? "The image is started by the digest recorded at review, so every session runs exactly the reviewed image. "
            : "The image digest is not recorded yet; publishing is refused until it is. ") : ""}
          Environment variables are never taken from the user&apos;s shell: a value comes from a named connection assigned to the
          Workspace, or the variable stays unset.
        </p>
      </div>
    </div>
  );
}
