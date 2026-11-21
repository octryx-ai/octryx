// Research strategy section: mode, source counts, search rounds, output size and delegation.
import { numberAt, stringAt } from "./researchPolicySpecHelpers";
import {
  FieldLabel,
  type ResearchPolicySectionProps,
} from "./researchPolicyFormShared";
import { CITATION_STYLE_OPTIONS, SOURCE_MODE_OPTIONS } from "./researchPolicyOptions";

type StrategyProps = Omit<ResearchPolicySectionProps, "setListPath"> & { parseError: string };

// One numeric spec field: its value at `path` (or `fallback`), written back through setNumberPath.
function NumberField({ spec, setNumberPath, label, path, fallback, min, max }: Pick<StrategyProps, "spec" | "setNumberPath"> & {
  label: string;
  path: string[];
  fallback: number;
  min: number;
  max?: number;
}) {
  return (
    <label>
      <FieldLabel label={label} />
      <input
        className="admin-panel__input"
        type="number"
        min={min}
        max={max}
        value={numberAt(spec, path, fallback)}
        onChange={(event) => setNumberPath(path, event.target.value, fallback)}
      />
    </label>
  );
}

// The citation style of the written output.
function CitationStyleField({ spec, setPath }: Pick<StrategyProps, "spec" | "setPath">) {
  return (
    <label>
      <FieldLabel label="Citation style" />
      <select
        className="admin-panel__input"
        value={stringAt(
          spec,
          ["output_policy", "citation_style"],
          "ieee",
        )}
        onChange={(event) =>
          setPath(["output_policy", "citation_style"], event.target.value)
        }
      >
        {CITATION_STYLE_OPTIONS.map((style) => (
          <option key={style} value={style}>
            {style.toUpperCase()}
          </option>
        ))}
      </select>
    </label>
  );
}

export function ResearchPolicyStrategySection({
  spec,
  parseError,
  setPath,
  setNumberPath,
}: StrategyProps) {
  const field = { spec, setNumberPath };
  return (
    <section className="research-policy-admin__form-section">
      <div className="research-policy-admin__form-section-title">
        <span>Research strategy</span>
        <small>Controls scope, depth, and output size.</small>
      </div>
      <div className="research-policy-admin__form-grid">
        <label>
          <FieldLabel
            label="Mode"
            hint="Normal web, deep, or scientific literature."
          />
          <select
            className="admin-panel__input"
            value={stringAt(spec, ["research_strategy", "mode"], "research")}
            onChange={(event) =>
              setPath(["research_strategy", "mode"], event.target.value)
            }
            disabled={Boolean(parseError)}
          >
            {SOURCE_MODE_OPTIONS.map((mode) => (
              <option key={mode} value={mode}>
                {mode}
              </option>
            ))}
          </select>
        </label>
        <NumberField {...field} label="Min sources" path={["research_strategy", "min_source_count"]} fallback={1} min={1} />
        <NumberField {...field} label="Target sources" path={["research_strategy", "target_source_count"]} fallback={10} min={1} />
        <NumberField {...field} label="Max sources" path={["research_strategy", "max_source_count"]} fallback={24} min={1} />
        <NumberField {...field} label="Search rounds" path={["research_strategy", "max_search_rounds"]} fallback={4} min={1} max={20} />
        <NumberField {...field} label="Target pages" path={["output_policy", "target_pages", "target"]} fallback={8} min={1} />
        <CitationStyleField spec={spec} setPath={setPath} />
        <NumberField {...field} label="Child agents" path={["delegation_policy", "max_child_agents"]} fallback={3} min={0} max={5} />
      </div>
    </section>
  );
}
