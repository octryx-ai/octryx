import type { ReactNode } from "react";

import type { AssignmentPolicy, AssignmentSkill } from "../skillCatalog/skillDeliveryTypes";
import type { CategoryNode } from "../skillCatalog/skillCatalogTypes";
import {
  MODE_CHOICES, categoryChecked, categoryLocked, setMode, skillChecked, skillLocked, skillsIn, skillsOutsideTree, toggleBlocked,
  toggleCategory, toggleSkill,
} from "../skillCatalog/workspaceSkillsModel";

type PickProps = { draft: AssignmentPolicy; selectable: boolean; disabled: boolean; onChange: (next: AssignmentPolicy) => void };

// "Which skills this Workspace gets" (WP 2.7, mock `#screen-workspace`): the assignment mode, and the
// category / skill picker. A ticked category includes every skill published into it, now and later, so its child
// categories and skills show checked and locked. Blocking a skill always wins, in every mode but None.
export function WorkspaceSkillsPicker({ draft, categories, skills, disabled, onChange }: {
  draft: AssignmentPolicy;
  categories: CategoryNode[];
  skills: AssignmentSkill[];
  disabled: boolean;
  onChange: (next: AssignmentPolicy) => void;
}) {
  const selectable = draft.mode === "selected_only";
  const visible = (node: CategoryNode) => !node.archived || categoryChecked(draft, node);
  const roots = categories.filter(visible);
  const outside = skillsOutsideTree(skills, roots.map((root) => ({ ...root, children: root.children.filter(visible) })));
  const pick: PickProps = { draft, selectable, disabled, onChange };

  const groups: ReactNode[] = roots.map((root) => (
    <CategoryGroup key={root.id} root={root} visibleChildren={root.children.filter(visible)} skills={skills} pick={pick} />
  ));

  return (
    <>
      <div className="policies__choice-grid" style={{ gridTemplateColumns: "repeat(3,minmax(0,1fr))" }} data-testid="ws-mode">
        {MODE_CHOICES.map((choice) => (
          <button key={choice.mode} type="button" disabled={disabled} data-testid={`ws-mode-${choice.mode}`}
            className={`policies__choice${draft.mode === choice.mode ? " policies__choice--selected" : ""}`}
            aria-pressed={draft.mode === choice.mode}
            onClick={() => onChange(setMode(draft, choice.mode))}>
            <b>{choice.title}</b><span>{choice.text}</span>
          </button>
        ))}
      </div>
      {draft.mode === "none" ? null : (
        <div data-testid="ws-picker">
          <p className="skills__hint" style={{ marginTop: ".4rem" }}>
            {selectable
              ? "Tick a category to assign all of its published entries, including entries published later. Tick single skills for anything else. Block keeps a skill out of this Workspace; blocking always wins."
              : "Every published skill is assigned. Block keeps a skill out of this Workspace; blocking always wins."}
          </p>
          {skills.length || selectable ? (
            <div className="skills__ws-cols" style={{ columns: 2, columnGap: "1rem" }}>
              {groups}
              {outside.length ? (
                <div style={{ breakInside: "avoid", marginBottom: ".4rem" }}>
                  <div className="skills__cbx"><b>Other</b></div>
                  {outside.map((skill) => <SkillRow key={skill.id} skill={skill} indent="skills__cbx--child" pick={pick} />)}
                </div>
              ) : null}
            </div>
          ) : <div className="admin-panel__empty-state">No published skills in the catalog yet.</div>}
        </div>
      )}
    </>
  );
}

// A root category with its own skills and its visible child categories; nothing when it has no skill to show.
function CategoryGroup({ root, visibleChildren: children, skills, pick }: {
  root: CategoryNode;
  visibleChildren: CategoryNode[];
  skills: AssignmentSkill[];
  pick: PickProps;
}) {
  const own = skillsIn(skills, root.key);
  const hasSkills = own.length || children.some((child) => skillsIn(skills, child.key).length);
  if (!pick.selectable && !hasSkills) return null;
  return (
    <div style={{ breakInside: "avoid", marginBottom: ".4rem" }}>
      <CategoryRow node={root} child={false} pick={pick} />
      {own.map((skill) => <SkillRow key={skill.id} skill={skill} indent="skills__cbx--child" pick={pick} />)}
      {children.map((child) => (
        <div key={child.id}>
          {pick.selectable || skillsIn(skills, child.key).length ? <CategoryRow node={child} child pick={pick} /> : null}
          {skillsIn(skills, child.key).map((skill) => <SkillRow key={skill.id} skill={skill} indent="skill-tabs__deep" pick={pick} />)}
        </div>
      ))}
    </div>
  );
}

function SkillRow({ skill, indent, pick: { draft, selectable, disabled, onChange } }: { skill: AssignmentSkill; indent: string; pick: PickProps }) {
  const blocked = draft.blocked_skill_ids.includes(skill.id);
  const name = (
    <>
      <span className={`skills__mono${blocked ? " skill-tabs__blocked" : ""}`}>{skill.name}</span>
      {skill.kind === "mcp_server" ? <span className="skills__kind">MCP</span> : null}
    </>
  );
  return (
    <div className={`skill-tabs__skill ${indent}`} title={skill.description} data-testid={`ws-skill-${skill.name}`}>
      {selectable ? (
        <label className="skills__cbx">
          <input type="checkbox" checked={skillChecked(draft, skill)} disabled={disabled || skillLocked(draft, skill)}
            onChange={() => onChange(toggleSkill(draft, skill.id))} />
          {name}
        </label>
      ) : <span className="skills__cbx">{name}</span>}
      <label className="skill-tabs__block">
        <input type="checkbox" checked={blocked} disabled={disabled} aria-label={`Block ${skill.name}`}
          onChange={() => onChange(toggleBlocked(draft, skill.id))} data-testid={`ws-block-${skill.name}`} />
        Block
      </label>
    </div>
  );
}

function CategoryRow({ node, child, pick: { draft, selectable, disabled, onChange } }: { node: CategoryNode; child: boolean; pick: PickProps }) {
  const label = child ? <span>{node.label}</span> : <b>{node.label}</b>;
  if (!selectable) return <div className={`skills__cbx${child ? " skills__cbx--child" : ""}`}>{label}</div>;
  return (
    <label className={`skills__cbx${child ? " skills__cbx--child" : ""}`} data-testid={`ws-category-${node.key}`}>
      <input type="checkbox" checked={categoryChecked(draft, node)} disabled={disabled || (child && categoryLocked(draft, node))}
        onChange={() => onChange(toggleCategory(draft, node.key))} />
      {label}<span className="skills__hint">whole category</span>
    </label>
  );
}
