import { SURFACE_LABELS } from "./skillCatalogTypes";
import { descriptionIssue, flattenCategories, nameIssue } from "./skillCatalogModel";
import type { CategoryCatalog, Surface } from "./skillCatalogTypes";
import { DESCRIPTION_MAX, EDITOR_SECTIONS, contractProblems } from "./skillEditorModel";
import type { EditorForm, ToolLists } from "./skillEditorModel";

const TOOL_HINTS: Record<Surface, string> = {
  platform_chat: "Platform chat tool names, one per line",
  octryx_claude: "Claude Code permission patterns, one per line",
};

type Patch = (change: Partial<EditorForm>) => void;

// The middle column of the skill editor (mock `openEditor`): the Agent Skills frontmatter fields, the
// instructions body, the Octryx fields (tools per surface, roles, output contract, safety rules) and the
// availability per surface. Execution keys (`allowed-tools`, `hooks`, `model`, …) are deliberately not fields.
export function SkillEditorFields({ form, isNew, licence, categories, onChange }: {
  form: EditorForm;
  isNew: boolean;
  licence: string;
  categories: CategoryCatalog;
  onChange: Patch;
}) {
  return (
    <div className="admin-panel__stack" style={{ minWidth: 0 }}>
      <FrontmatterSection form={form} isNew={isNew} licence={licence} onChange={onChange} />

      <section className="admin-panel__card" id={EDITOR_SECTIONS[1].id}>
        <div className="admin-panel__section-header">Instructions (SKILL.md body)</div>
        <textarea className="skills__textarea" value={form.body} data-testid="skill-editor-body" spellCheck={false}
          placeholder="Markdown instructions the agent follows once the skill is loaded"
          onChange={(event) => onChange({ body: event.target.value })} />
      </section>

      <OctryxFieldsSection form={form} categories={categories} onChange={onChange} />

      <AvailabilitySection form={form} isNew={isNew} onChange={onChange} />
    </div>
  );
}

type SectionProps = { form: EditorForm; onChange: Patch };

function FrontmatterSection({ form, isNew, licence, onChange }: SectionProps & { isNew: boolean; licence: string }) {
  const nameProblem = isNew && form.name ? nameIssue(form.name.trim()) : null;
  const descriptionProblem = form.description ? descriptionIssue(form.description) : null;
  return (
    <section className="admin-panel__card" id={EDITOR_SECTIONS[0].id}>
      <div className="admin-panel__section-header">Agent Skills fields (SKILL.md frontmatter)</div>
      <div className="admin-panel__form-grid">
        <label className="admin-panel__field">
          <span>Name</span>
          <input className="skills__mono" value={form.name} readOnly={!isNew} data-testid="skill-editor-name"
            placeholder="lower-case-with-hyphens" aria-invalid={nameProblem ? true : undefined}
            onChange={(event) => onChange({ name: event.target.value })} />
          {nameProblem ? <small className="skills__er">{nameProblem}</small> : null}
          {!isNew ? <small className="skills__hint">The name of a skill cannot change.</small> : null}
        </label>
        <label className="admin-panel__field">
          <span>Licence (SPDX)</span>
          <input value={licence} readOnly data-testid="skill-editor-licence" />
          <small className="skills__hint">{isNew ? "Skills written here are Internal." : "Detected from the source; not editable here."}</small>
        </label>
      </div>
      <label className="admin-panel__field">
        <span>Description: what it does and when to use it</span>
        <textarea rows={3} value={form.description} data-testid="skill-editor-description"
          aria-invalid={descriptionProblem ? true : undefined}
          onChange={(event) => onChange({ description: event.target.value })} />
      </label>
      <div className={`skills__counter${form.description.length > DESCRIPTION_MAX ? " skills__er" : ""}`}>
        {form.description.length} / {DESCRIPTION_MAX}
      </div>
      <label className="admin-panel__field">
        <span>When to use (optional)</span>
        <textarea rows={2} value={form.whenToUse} data-testid="skill-editor-when"
          placeholder="Situations or requests where the agent should load this skill"
          onChange={(event) => onChange({ whenToUse: event.target.value })} />
      </label>
      <p className="skills__hint">Frontmatter keys that grant tools or change the execution context (allowed-tools, hooks, model, …)
        are not offered here; they are stripped on delivery. Other keys of an imported SKILL.md are kept as they are.</p>
    </section>
  );
}

function OctryxFieldsSection({ form, categories, onChange }: SectionProps & { categories: CategoryCatalog }) {
  const contractIssues = contractProblems(form.outputContract);
  const options = flattenCategories(categories.categories).filter((node) => !node.archived);
  return (
    <details className="policies__advanced admin-panel__card" open id={EDITOR_SECTIONS[2].id}>
      <summary>Octryx fields</summary>
      <div className="admin-panel__form-grid">
        <label className="admin-panel__field">
          <span>Category</span>
          <select value={form.categoryId} data-testid="skill-editor-category" required
            onChange={(event) => onChange({ categoryId: event.target.value })}>
            <option value="">Choose a category…</option>
            {options.map((node) => <option key={node.id} value={node.id}>{node.fullLabel}</option>)}
          </select>
        </label>
        <label className="admin-panel__field">
          <span>Tags</span>
          <input value={form.tags} data-testid="skill-editor-tags" placeholder="Comma-separated"
            onChange={(event) => onChange({ tags: event.target.value })} />
        </label>
        {(["octryx_claude", "platform_chat"] as Surface[]).map((surface) => (
          <SurfaceTools key={surface} surface={surface} form={form} onChange={onChange} />
        ))}
        <label className="admin-panel__field">
          <span>Roles that may use it</span>
          <input value={form.roles} data-testid="skill-editor-roles" placeholder="Comma-separated; empty means every role"
            onChange={(event) => onChange({ roles: event.target.value })} />
        </label>
        <label className="admin-panel__field">
          <span>Output contract</span>
          <textarea rows={2} className="skills__mono" value={form.outputContract} data-testid="skill-editor-contract"
            placeholder="One key: value per line"
            onChange={(event) => onChange({ outputContract: event.target.value })} />
          {contractIssues.length ? <small className="skills__wa">Lines without key: value are dropped: {contractIssues.join(" · ")}</small> : null}
        </label>
      </div>
      <label className="admin-panel__field">
        <span>Safety rules (one per line; appended to the instructions on both surfaces)</span>
        <textarea rows={3} value={form.safetyRules} data-testid="skill-editor-safety"
          onChange={(event) => onChange({ safetyRules: event.target.value })} />
      </label>
      <p className="skills__hint">Tools only feed the readiness view and the required-tools check; they are never delivered as
        allowed-tools and never widen what a Workspace may run.</p>
    </details>
  );
}

function SurfaceTools({ surface, form, onChange }: SectionProps & { surface: Surface }) {
  const setTools = (change: Partial<ToolLists>) =>
    onChange({ tools: { ...form.tools, [surface]: { ...form.tools[surface], ...change } } });
  return (
    <div style={{ display: "contents" }}>
      <label className="admin-panel__field">
        <span>Required tools · {SURFACE_LABELS[surface]}</span>
        <textarea rows={2} className="skills__mono" value={form.tools[surface].required} placeholder={TOOL_HINTS[surface]}
          data-testid={`skill-editor-tools-${surface}-required`}
          onChange={(event) => setTools({ required: event.target.value })} />
      </label>
      <label className="admin-panel__field">
        <span>Optional tools · {SURFACE_LABELS[surface]}</span>
        <textarea rows={2} className="skills__mono" value={form.tools[surface].optional} placeholder={TOOL_HINTS[surface]}
          data-testid={`skill-editor-tools-${surface}-optional`}
          onChange={(event) => setTools({ optional: event.target.value })} />
      </label>
    </div>
  );
}

function AvailabilitySection({ form, isNew, onChange }: SectionProps & { isNew: boolean }) {
  return (
    <section className="admin-panel__card" id={EDITOR_SECTIONS[3].id}>
      <div className="admin-panel__section-header">Availability</div>
      <SurfaceSwitch label={SURFACE_LABELS.platform_chat} hint="Found with skill_search and loaded with skill_get."
        on={form.availablePlatformChat} testId="skill-editor-available-platform_chat"
        onToggle={() => onChange({ availablePlatformChat: !form.availablePlatformChat })} />
      <SurfaceSwitch label={SURFACE_LABELS.octryx_claude} hint="Delivered in the octryx plugin at session start."
        on={form.availableOctryxClaude} testId="skill-editor-available-octryx_claude"
        onToggle={() => onChange({ availableOctryxClaude: !form.availableOctryxClaude })} />
      {!isNew ? (
        <label className="admin-panel__field" style={{ marginTop: ".6rem" }}>
          <span>Change note (optional)</span>
          <input value={form.note} data-testid="skill-editor-note" placeholder="What changed and why"
            onChange={(event) => onChange({ note: event.target.value })} />
        </label>
      ) : null}
    </section>
  );
}

function SurfaceSwitch({ label, hint, on, testId, onToggle }: { label: string; hint: string; on: boolean; testId: string; onToggle: () => void }) {
  return (
    <div className="skills__toggle">
      <div>{label}<small>{hint}</small></div>
      <button type="button" role="switch" aria-checked={on} aria-label={`Available on ${label}`} data-testid={testId}
        className={`skills__switch${on ? " is-on" : ""}`} onClick={onToggle} />
    </div>
  );
}
