// User edit panel: group selection with its save button and removable group pills.
import type { Dispatch, SetStateAction } from "react";
import type { AdminIdentityGroupRow } from "./identityTypes";
import { MultiSelect } from "./UserEditMultiSelect";
import { SectionLabel } from "./userEditPanelParts";

type AdminUserGroupsSectionProps = {
  groups: AdminIdentityGroupRow[];
  selectedGroupIds: string[];
  setSelectedGroupIds: Dispatch<SetStateAction<string[]>>;
  groupsSaving: boolean;
  handleSaveGroups: () => Promise<void>;
};

export function AdminUserGroupsSection({
  groups, selectedGroupIds, setSelectedGroupIds, groupsSaving, handleSaveGroups,
}: AdminUserGroupsSectionProps) {
  return (
    <section className="user-edit-panel__section">
      <SectionLabel>Groups</SectionLabel>
      <div className="user-edit-panel__row">
        <MultiSelect
          options={groups}
          selectedIds={selectedGroupIds}
          onChange={setSelectedGroupIds}
          noun={{ one: "group", many: "groups" }}
        />
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={() => void handleSaveGroups()}
          disabled={groupsSaving}
        >
          {groupsSaving ? "Saving…" : "Save"}
        </button>
      </div>
      {selectedGroupIds.length > 0 && (
        <div className="user-edit-panel__group-pills">
          {selectedGroupIds.map((id) => {
            const g = groups.find((x) => x.id === id);
            if (!g) return null;
            return (
              <span key={id} className="user-edit-panel__group-pill">
                {g.name}
                <button
                  type="button"
                  aria-label={`Remove ${g.name}`}
                  onClick={() =>
                    setSelectedGroupIds((prev) =>
                      prev.filter((x) => x !== id),
                    )
                  }
                >
                  ×
                </button>
              </span>
            );
          })}
        </div>
      )}
    </section>
  );
}
