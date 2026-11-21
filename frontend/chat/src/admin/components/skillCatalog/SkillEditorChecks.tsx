import { SkillMarkdown } from "./SkillMarkdown";
import { formatSize } from "./skillCatalogModel";
import type { FileEntry } from "./skillCatalogTypes";
import { CHECK_ICONS, EDITOR_SECTIONS } from "./skillEditorModel";
import type { EditorCheck } from "./skillEditorModel";

// The left column of the skill editor (mock `openEditor`): the section nav and the draft's files. Only the
// SKILL.md is edited here; reference files come from an import or an upload.
export function SkillEditorNav({ files }: { files: FileEntry[] }) {
  const jump = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  const others = files.filter((file) => file.path !== "SKILL.md");
  return (
    <nav className="admin-panel__card" style={{ padding: ".4rem" }} aria-label="Editor sections" data-testid="skill-editor-nav">
      <div className="skills__files">
        {EDITOR_SECTIONS.map((section) => (
          <button key={section.id} type="button" className="skills__file skills__editor-nav-btn"
            onClick={() => jump(section.id)}>{section.label}</button>
        ))}
      </div>
      <div className="skills__tree-label" style={{ marginTop: ".5rem" }}>Files</div>
      <div className="skills__files" data-testid="skill-editor-files">
        <div className="skills__file is-active">SKILL.md</div>
        {others.map((file) => (
          <div key={file.path} className="skills__file" style={{ cursor: "default" }}>
            {file.path}<span className="skills__file-meta">{formatSize(file.size)}</span>
          </div>
        ))}
      </div>
      {others.length ? <p className="skills__hint" style={{ padding: ".3rem .5rem" }}>Reference files are kept as they are.</p> : null}
    </nav>
  );
}

// The right column of the skill editor: the live spec checks and a display-only preview of the SKILL.md the save
// would write (rendered through SkillMarkdown, so raw HTML is never rendered).
export function SkillEditorChecks({ checks, skillMd }: { checks: EditorCheck[]; skillMd: string }) {
  return (
    <aside className="policies__side">
      <div className="admin-panel__card">
        <div className="admin-panel__section-header">Checks</div>
        <div data-testid="skill-editor-checks">
          {checks.map((check) => (
            <div key={check.id} className="skills__check" data-check={check.id} data-tone={check.tone}>
              <span className={`skills__check-i skills__${check.tone}`} aria-hidden="true">{CHECK_ICONS[check.tone]}</span>
              <span>{check.text}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="admin-panel__card">
        <div className="admin-panel__section-header">Preview</div>
        <SkillMarkdown text={skillMd} maxHeight="20rem" testId="skill-editor-preview" />
      </div>
    </aside>
  );
}
