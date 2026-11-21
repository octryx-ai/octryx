// Research policy requests: load the policy list with its selection, run a saving action, create a profile.
import type { Dispatch, SetStateAction } from "react";
import { readJson } from "../utils/adminPanelHelpers";
import type {
  ResearchPolicyListPayload,
  ResearchPolicyProfile,
} from "../types/researchPolicyTypes";
import { formatSpec, parseSpecDraft } from "./researchPolicyDrafts";

type Setter<T> = Dispatch<SetStateAction<T>>;

export type ResearchPolicyLoadSetters = {
  setPayload: Setter<ResearchPolicyListPayload>;
  setLoading: Setter<boolean>;
  setError: Setter<string | null>;
  setSelectedProfileId: Setter<string>;
  setSelectedVersionId: Setter<string>;
  setSpecDraft: Setter<string>;
};

// Keeps the current profile/version when still present, else the default profile and its published version.
export async function fetchResearchPolicies(
  s: ResearchPolicyLoadSetters,
  selectedProfileId: string,
  selectedVersionId: string,
) {
  s.setLoading(true);
  s.setError(null);
  try {
    const nextPayload = await readJson<ResearchPolicyListPayload>(
      "/admin/chat/api/panel/research-policies",
    );
    s.setPayload(nextPayload);
    const nextProfile =
      nextPayload.profiles.find((profile) => profile.id === selectedProfileId) ||
      nextPayload.profiles.find((profile) => profile.key === nextPayload.defaults.default_profile_key) ||
      nextPayload.profiles[0];
    if (nextProfile) {
      s.setSelectedProfileId(nextProfile.id);
      const nextVersion =
        nextProfile.versions.find((version) => version.id === selectedVersionId) ||
        nextProfile.versions.find((version) => version.id === nextProfile.latest_published_version_id) ||
        nextProfile.versions[0];
      if (nextVersion) {
        s.setSelectedVersionId(nextVersion.id);
        s.setSpecDraft(formatSpec(nextVersion.spec));
      }
    }
  } catch (loadError) {
    s.setError(loadError instanceof Error ? loadError.message : "Failed to load research policies.");
  } finally {
    s.setLoading(false);
  }
}

export type ResearchPolicySavingSetters = {
  setSaving: Setter<boolean>;
  setError: Setter<string | null>;
  setNotice: Setter<string | null>;
};

// Resolves true when the action succeeded, so a create panel can close only then.
export async function runResearchPolicySaving(
  s: ResearchPolicySavingSetters,
  action: () => Promise<void>,
  success: string,
): Promise<boolean> {
  s.setSaving(true);
  s.setError(null);
  s.setNotice(null);
  try {
    await action();
    s.setNotice(success);
    return true;
  } catch (actionError) {
    s.setError(actionError instanceof Error ? actionError.message : "Request failed.");
    return false;
  } finally {
    s.setSaving(false);
  }
}

export type NewResearchProfile = {
  newProfileKey: string;
  newProfileName: string;
  newVersionNotes: string;
  specDraft: string;
  createAsPublished: boolean;
};

export function postResearchPolicyProfile(draft: NewResearchProfile) {
  return readJson<ResearchPolicyProfile>(
    "/admin/chat/api/panel/research-policies",
    {
      method: "POST",
      body: JSON.stringify({
        key: draft.newProfileKey.trim(),
        name: draft.newProfileName.trim() || draft.newProfileKey.trim(),
        initial_spec: parseSpecDraft(draft.specDraft),
        initial_version_status: draft.createAsPublished ? "published" : "draft",
        notes: draft.newVersionNotes.trim(),
      }),
    },
  );
}
