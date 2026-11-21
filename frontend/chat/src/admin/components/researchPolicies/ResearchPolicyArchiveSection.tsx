// Evidence archive section: folder layout preview and archive toggles.
import { booleanAt } from "./researchPolicySpecHelpers";
import type { ResearchPolicySectionProps } from "./researchPolicyFormShared";

// The archive switches under `evidence_archive`, each on unless the spec turns it off.
const ARCHIVE_TOGGLES = [
  ["preserve_raw_sources", "Preserve raw sources"],
  ["preserve_parsed_text", "Preserve parsed text"],
  ["write_source_manifests", "Write source manifests"],
  ["write_bundle_manifest", "Write bundle manifest"],
] as const;

export function ResearchPolicyArchiveSection({
  spec,
  archiveFolder,
  setPath,
}: Pick<ResearchPolicySectionProps, "spec" | "setPath"> & {
  archiveFolder: string;
}) {
  return (
    <section className="research-policy-admin__form-section">
      <div className="research-policy-admin__form-section-title">
        <span>Evidence archive</span>
        <small>
          New sources are stored in a deterministic source folder tree.
        </small>
      </div>
      <div className="research-policy-admin__archive-preview">
        <code>
          {archiveFolder}/&lt;bundle&gt;/sources/&lt;source-id-title&gt;/raw
        </code>
        <code>
          {archiveFolder}
          /&lt;bundle&gt;/sources/&lt;source-id-title&gt;/parsed
        </code>
        <code>
          {archiveFolder}
          /&lt;bundle&gt;/sources/&lt;source-id-title&gt;/evidence
        </code>
        <code>
          {archiveFolder}/&lt;bundle&gt;/sources.json · citations.json ·
          evidence_manifest.json
        </code>
      </div>
      <div className="research-policy-admin__toggle-grid">
        {ARCHIVE_TOGGLES.map(([key, label]) => (
          <label key={key}>
            <input
              type="checkbox"
              checked={booleanAt(spec, ["evidence_archive", key], true)}
              onChange={(event) => setPath(["evidence_archive", key], event.target.checked)}
            />
            {label}
          </label>
        ))}
      </div>
    </section>
  );
}
