// Scientific literature section: literature mode, peer-review toggles and domain/publication lists.
import {
  booleanAt,
  getSpecPath,
  listToText,
  stringAt,
} from "./researchPolicySpecHelpers";
import {
  FieldLabel,
  type ResearchPolicySectionProps,
} from "./researchPolicyFormShared";
import { LITERATURE_MODE_OPTIONS, SOURCE_MODE_OPTIONS } from "./researchPolicyOptions";

type LiteratureProps = Omit<ResearchPolicySectionProps, "setNumberPath">;

const LITERATURE = ["source_policy", "literature_policy"];

// The literature toggles in display order: spec key under literature_policy, default and label.
const LITERATURE_TOGGLES: { key: string; fallback: boolean; label: string }[] = [
  { key: "enabled", fallback: false, label: "Enable literature policy" },
  { key: "require_published_sources", fallback: false, label: "Published only" },
  { key: "require_peer_reviewed_sources", fallback: false, label: "Peer-reviewed only" },
  { key: "exclude_preprints", fallback: true, label: "Exclude preprints/drafts" },
  { key: "restrict_to_preferred_domains", fallback: false, label: "Restrict to preferred domains" },
];

// The literature lists in display order: spec key under literature_policy, label and optional hint.
const LITERATURE_LISTS: { key: string; label: string; hint?: string }[] = [
  { key: "preferred_domains", label: "Preferred scholarly domains", hint: "One domain per line or comma-separated." },
  { key: "preferred_databases", label: "Preferred databases", hint: "Examples: Semantic Scholar, OpenAlex, Crossref, PubMed." },
  { key: "allowed_publication_types", label: "Allowed publication types" },
  { key: "excluded_publication_types", label: "Excluded publication types" },
];

function LiteratureModeFields({ spec, setPath }: Pick<LiteratureProps, "spec" | "setPath">) {
  return (
    <div className="research-policy-admin__form-grid">
      <label>
        <FieldLabel label="Literature mode" />
        <select
          className="admin-panel__input"
          value={stringAt(spec, [...LITERATURE, "mode"], "auto")}
          onChange={(event) => setPath([...LITERATURE, "mode"], event.target.value)}
        >
          {LITERATURE_MODE_OPTIONS.map((mode) => (
            <option key={mode} value={mode}>
              {mode}
            </option>
          ))}
        </select>
      </label>
      <label>
        <FieldLabel label="Research mode override" />
        <select
          className="admin-panel__input"
          value={stringAt(spec, ["source_policy", "research_mode"], "")}
          onChange={(event) =>
            setPath(["source_policy", "research_mode"], event.target.value)
          }
        >
          <option value="">Follow strategy</option>
          {SOURCE_MODE_OPTIONS.map((mode) => (
            <option key={mode} value={mode}>
              {mode}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

function LiteratureToggles({ spec, setPath }: Pick<LiteratureProps, "spec" | "setPath">) {
  return (
    <div className="research-policy-admin__toggle-grid">
      {LITERATURE_TOGGLES.map((toggle) => (
        <label key={toggle.key}>
          <input
            type="checkbox"
            checked={booleanAt(spec, [...LITERATURE, toggle.key], toggle.fallback)}
            onChange={(event) => setPath([...LITERATURE, toggle.key], event.target.checked)}
          />
          {toggle.label}
        </label>
      ))}
    </div>
  );
}

function LiteratureLists({ spec, setListPath }: Pick<LiteratureProps, "spec" | "setListPath">) {
  return (
    <div className="research-policy-admin__list-grid">
      {LITERATURE_LISTS.map((list) => (
        <label key={list.key}>
          <FieldLabel label={list.label} hint={list.hint} />
          <textarea
            className="admin-panel__textarea"
            value={listToText(getSpecPath(spec, [...LITERATURE, list.key]))}
            onChange={(event) => setListPath([...LITERATURE, list.key], event.target.value)}
          />
        </label>
      ))}
    </div>
  );
}

export function ResearchPolicyLiteratureSection({
  spec,
  literaturePolicy,
  setPath,
  setListPath,
}: LiteratureProps & {
  literaturePolicy: unknown;
}) {
  return (
    <section className="research-policy-admin__form-section research-policy-admin__form-section--accent">
      <div className="research-policy-admin__form-section-title">
        <span>Scientific literature</span>
        <small>
          Use this when papers and peer-reviewed literature should be limited
          explicitly.
        </small>
      </div>
      <LiteratureModeFields spec={spec} setPath={setPath} />
      <LiteratureToggles spec={spec} setPath={setPath} />
      <LiteratureLists spec={spec} setListPath={setListPath} />
      {!literaturePolicy ? (
        <p className="admin-panel__hint">
          No literature policy exists yet. Changing a field here will create
          it without removing custom JSON fields.
        </p>
      ) : null}
    </section>
  );
}
