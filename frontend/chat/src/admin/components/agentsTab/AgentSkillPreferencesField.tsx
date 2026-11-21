import { useMemo, useState } from "react";

import type { SkillRow } from "../skillCatalog/skillCatalogTypes";

type PreferenceMode = "none" | "preferred" | "blocked";

type AgentSkillPreferencesFieldProps = {
  skills: SkillRow[];
  preferredSkillIds: string[];
  blockedSkillIds: string[];
  setPreferredSkillIds: (ids: string[]) => void;
  setBlockedSkillIds: (ids: string[]) => void;
};

function modeForSkill(
  skillId: string,
  preferredSkillIds: string[],
  blockedSkillIds: string[],
): PreferenceMode {
  if (blockedSkillIds.includes(skillId)) return "blocked";
  if (preferredSkillIds.includes(skillId)) return "preferred";
  return "none";
}

function withoutId(values: string[], skillId: string) {
  return values.filter((value) => value !== skillId);
}

export function AgentSkillPreferencesField({
  skills,
  preferredSkillIds,
  blockedSkillIds,
  setPreferredSkillIds,
  setBlockedSkillIds,
}: AgentSkillPreferencesFieldProps) {
  const [search, setSearch] = useState("");
  const visibleSkills = useMemo(() => {
    const needle = search.trim().toLowerCase();
    // Skills with a published or an open version; a retired-only skill has neither.
    const liveSkills = skills.filter((skill) => skill.published || skill.open);
    if (!needle) return liveSkills;
    return liveSkills.filter((skill) =>
      [
        skill.name,
        skill.description,
        ...(skill.category?.path ?? []),
        ...skill.tags,
      ]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [search, skills]);

  const setMode = (skillId: string, mode: PreferenceMode) => {
    setPreferredSkillIds(withoutId(preferredSkillIds, skillId));
    setBlockedSkillIds(withoutId(blockedSkillIds, skillId));
    if (mode === "preferred") {
      setPreferredSkillIds([...withoutId(preferredSkillIds, skillId), skillId]);
    } else if (mode === "blocked") {
      setBlockedSkillIds([...withoutId(blockedSkillIds, skillId), skillId]);
    }
  };

  return (
    <div className="task-form__field task-form__field--full">
      <label className="admin-panel__form-label">
        Skill discovery preferences
      </label>
      <p className="admin-panel__hint">
        The Workspace assignment is the only grant; an agent only narrows it:
        preferred skills rank first in skill_search, blocked skills are hidden.
      </p>
      <input
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        className="connector-field__input"
        placeholder="Search catalog skills"
      />
      <div className="connector-policy__catalog connector-policy__catalog--standalone">
        {visibleSkills.map((skill) => (
          <div key={skill.id} className="connector-policy__catalog-item">
            <div>
              <div className="connector-tool__name">{skill.name}</div>
              <div className="connector-tool__desc">
                {skill.description || "No description"} - {skill.category?.path.join(" / ") || "Uncategorized"} -{" "}
                {skill.published ? `v${skill.published.version}` : "not published"}
              </div>
            </div>
            <select
              value={modeForSkill(
                skill.id,
                preferredSkillIds,
                blockedSkillIds,
              )}
              onChange={(event) =>
                setMode(skill.id, event.target.value as PreferenceMode)
              }
              className="connector-field__input"
            >
              <option value="none">None</option>
              <option value="preferred">Preferred</option>
              <option value="blocked">Blocked</option>
            </select>
          </div>
        ))}
        {visibleSkills.length === 0 ? (
          <div className="admin-panel__empty">No matching skills.</div>
        ) : null}
      </div>
    </div>
  );
}
