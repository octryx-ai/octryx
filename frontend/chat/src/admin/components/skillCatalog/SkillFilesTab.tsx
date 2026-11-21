import { useState } from "react";

import { SkillMarkdown } from "./SkillMarkdown";
import { formatSize, shortDigest } from "./skillCatalogModel";
import type { SkillVersion } from "./skillCatalogTypes";
import { fileKindLabel } from "./skillDetailModel";
import { useSkillFile } from "./useSkillFile";
import type { FileState } from "./useSkillFile";

/** A loaded file: Markdown rendered (raw HTML never), everything else verbatim in a <pre>. */
export function FileContent({ path, file, testId }: { path: string; file: FileState; testId?: string }) {
  if (file.loading) return <p className="admin-panel__hint" role="status">Loading {path}…</p>;
  if (file.problem) return <p className="policies__warn" role="alert">{file.problem}</p>;
  if (file.content === null) return null;
  if (path.toLowerCase().endsWith(".md")) return <SkillMarkdown text={file.content} testId={testId} />;
  return <pre className="policies__code skill-detail__pre" data-testid={testId}>{file.content}</pre>;
}

// Detail → Files (mock `FILES`/`fileBody`): every file of the working version with kind, size and short digest;
// clicking one shows its content. A script that is withheld is marked so on the list and above its text.
export function SkillFilesTab({ skillId, version }: { skillId: string; version: SkillVersion }) {
  const first = version.files.find((file) => file.kind === "instructions")?.path ?? version.files[0]?.path ?? null;
  const [selected, setSelected] = useState<string | null>(first);
  const file = useSkillFile(skillId, version.version, selected);
  const entry = version.files.find((item) => item.path === selected) ?? null;
  if (!version.files.length) return <div className="admin-panel__empty-state">This version has no files.</div>;
  return (
    <div data-testid="skill-files">
      <div className="admin-panel__card" style={{ padding: ".4rem" }}>
        <div className="skills__files">
          {version.files.map((item) => (
            <button key={item.path} type="button" className={`skills__file skill-detail__file${selected === item.path ? " is-active" : ""}`}
              aria-pressed={selected === item.path} data-testid={`skill-file-${item.path}`} onClick={() => setSelected(item.path)}>
              {item.path}
              <span className="skills__file-meta">{fileKindLabel(item, version.scripts_allowed)} · {formatSize(item.size)} · {shortDigest(item.sha256)}</span>
            </button>
          ))}
        </div>
      </div>
      {entry?.kind === "script" && !version.scripts_allowed ? (
        <div className="policies__warn skill-detail__gap"><b>Withheld.</b> This script is not delivered to any surface unless a platform
          admin allows scripts for this version (Security tab).</div>
      ) : null}
      {selected ? <div className="skill-detail__gap"><FileContent path={selected} file={file} testId="skill-file-content" /></div> : null}
    </div>
  );
}
