import { useEffect, useState } from "react";

import type { AdminProjectQuality } from "../../types/projectQualityTypes";
import { DEFAULT_KNOWLEDGE_LOOKUP_DEFAULTS, clampNumber, normalizeKnowledgeLookupConfig } from "./knowledgeLookupModel";
import type { KnowledgeLookupConfig, SavedKnowledgeLookupDefaults } from "./knowledgeLookupModel";

type ReadJson = <T = unknown>(url: string, init?: RequestInit) => Promise<T>;

type SaveSetters = { setSaving: (value: boolean) => void; setSaved: (value: boolean) => void; setError: (value: string | null) => void };

// PUT the limits; "saved" shows for three seconds.
async function saveLookupDefaults(project: AdminProjectQuality | null, readJson: ReadJson, defaults: SavedKnowledgeLookupDefaults,
  { setSaving, setSaved, setError }: SaveSetters) {
  if (!project?.id || !readJson) return;
  setSaving(true);
  setSaved(false);
  setError(null);

  try {
    await readJson(
      `/admin/chat/api/panel/projects/${project.id}/config`,
      {
        method: "PUT",
        body: JSON.stringify({
          knowledge_lookup: defaults,
        }),
      },
    );
    setSaved(true);
    window.setTimeout(() => setSaved(false), 3000);
  } catch (err) {
    setError(
      err instanceof Error
        ? err.message
        : "Failed to save knowledge lookup defaults",
    );
  } finally {
    setSaving(false);
  }
}

// The Workspace's knowledge lookup limits: loaded per Workspace, edited within their ranges, saved as one config.
export function useKnowledgeLookupDefaults(project: AdminProjectQuality | null, readJson: ReadJson) {
  const [defaults, setDefaults] =
    useState<SavedKnowledgeLookupDefaults>(DEFAULT_KNOWLEDGE_LOOKUP_DEFAULTS);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!project?.id || !readJson) return;

    (async () => {
      setError(null);
      try {
        const data = await readJson<KnowledgeLookupConfig>(
          `/admin/chat/api/panel/projects/${project.id}/config`,
        );
        setDefaults(normalizeKnowledgeLookupConfig(data.config.knowledge_lookup));
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Failed to load knowledge lookup defaults",
        );
      }
    })();
  }, [project?.id, readJson]);

  const handleSave = () => saveLookupDefaults(project, readJson, defaults, { setSaving, setSaved, setError });

  const updateDefault = (
    key: keyof SavedKnowledgeLookupDefaults,
    value: number,
    min: number,
    max: number,
  ) => {
    setDefaults((current) => ({
      ...current,
      [key]: clampNumber(value, min, max, current[key]),
    }));
    setSaved(false);
  };

  return { defaults, saving, saved, error, handleSave, updateDefault };
}
