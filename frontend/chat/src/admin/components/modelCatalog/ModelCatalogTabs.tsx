import type { ContentCategory } from "../providerTab/litellmGatewayApprovedCategories";
import { CatalogSwitch } from "./CatalogSwitch";
import {
  CAPABILITY_KEYS,
  CAPABILITY_LABELS,
  COST_SOURCES,
  COST_SOURCE_LABELS,
  TEMPERATURE_CHOICES,
  issueText,
  levelLabel,
  priceText,
} from "./modelCatalogContract";
import type { CatalogRow, CostSource, ModelDraft } from "./modelCatalogContract";

// The four tabs of the model drawer (mock: General · Data · Generation · Cost).

type TabProps = { row: CatalogRow; draft: ModelDraft; onDraft: (patch: Partial<ModelDraft>) => void };

export function GeneralTab({ row, draft, onDraft }: TabProps) {
  return (
    <div className="admin-panel__stack">
      {row.issues.length ? (
        <div className="model-catalog__warn" role="status">{row.issues.map(issueText).join(". ")}.</div>
      ) : null}
      <div className="model-catalog__bar">
        <span>
          <b>Enabled</b>
          <div className="model-catalog__sub">Workspaces can choose it once it is cleared for their data class.</div>
        </span>
        <CatalogSwitch on={draft.enabled} label="Enabled" testId="catalog-enabled"
          onChange={(enabled) => onDraft({ enabled })} />
      </div>
      <label className="admin-panel__field">
        <span>Display name</span>
        <input value={draft.displayName} maxLength={80} data-testid="catalog-display-name"
          onChange={(event) => onDraft({ displayName: event.target.value })} />
      </label>
      <div className="admin-panel__field">
        <span>Capabilities</span>
        <div className="model-catalog__chips">
          {CAPABILITY_KEYS.map((key) => (
            <label key={key} className="admin-panel__checkbox">
              <input type="checkbox" checked={draft.capabilities[key]} data-testid={`catalog-capability-${key}`}
                onChange={(event) => onDraft({ capabilities: { ...draft.capabilities, [key]: event.target.checked } })} />
              {CAPABILITY_LABELS[key]}
            </label>
          ))}
        </div>
      </div>
      <p className="model-catalog__sub">
        Workflows that need coding run only on models with Coding ticked. A model's name never decides this.
      </p>
      <details className="model-catalog__details">
        <summary className="model-catalog__sub">Technical details</summary>
        <dl className="work-detail__kv">
          <dt>Provider id</dt>
          <dd><code className="admin-policy-inline-code">{row.modelId}</code></dd>
          <dt>Catalog key</dt>
          <dd><code className="admin-policy-inline-code">{row.catalogKey}</code></dd>
          <dt>Context</dt>
          <dd>{row.contextLength ? `${row.contextLength.toLocaleString("en-US")} tokens` : "—"}</dd>
          {row.issues.filter((issue) => issue.detail).map((issue) => (
            <div key={issue.code}>
              <dt>Admission code</dt>
              <dd><code className="admin-policy-inline-code">{issue.detail}</code></dd>
            </div>
          ))}
        </dl>
      </details>
    </div>
  );
}

export function DataTab({ draft, onDraft, levels, categories }: TabProps & { levels: string[]; categories: ContentCategory[] }) {
  const options = [
    ...categories,
    ...draft.approvedFor.filter((id) => !categories.some((item) => item.id === id)).map((id) => ({ id, label: id })),
  ];
  const toggle = (id: string, on: boolean) =>
    onDraft({ approvedFor: on ? [...draft.approvedFor, id].sort() : draft.approvedFor.filter((item) => item !== id) });
  return (
    <div className="admin-panel__stack">
      <label className="admin-panel__field">
        <span>Cleared up to</span>
        <select value={draft.clearedUpTo ?? ""} data-testid="catalog-cleared-up-to"
          onChange={(event) => onDraft({ clearedUpTo: event.target.value || null })}>
          <option value="">Not cleared</option>
          {levels.map((level) => <option key={level} value={level}>{levelLabel(level)}</option>)}
        </select>
      </label>
      <p className="model-catalog__sub">
        This model may process data up to this class. The Classification policy shows this read-only in its
        "Company models" column.
      </p>
      <div className="admin-panel__field">
        <span>Approved for special categories</span>
        <div className="model-catalog__chips">
          {options.length ? options.map((item) => (
            <label key={item.id} className="admin-panel__checkbox">
              <input type="checkbox" checked={draft.approvedFor.includes(item.id)} data-testid={`catalog-approved-${item.id}`}
                onChange={(event) => toggle(item.id, event.target.checked)} />
              {item.label}
            </label>
          )) : <span className="model-catalog__sub">No content categories are defined.</span>}
        </div>
      </div>
      <div className="model-catalog__note">
        Content policies (Settings → Governance → Policies) re-route messages with these categories only to models
        approved here.
      </div>
    </div>
  );
}

export function GenerationTab({ row, draft, onDraft }: TabProps) {
  const choices = TEMPERATURE_CHOICES.some((choice) => choice.value === draft.temperature)
    ? TEMPERATURE_CHOICES
    : [...TEMPERATURE_CHOICES, { value: draft.temperature, label: String(draft.temperature) }];
  return (
    <div className="admin-panel__stack">
      <div className="admin-panel__form-grid">
        <label className="admin-panel__field">
          <span>Temperature</span>
          <select value={draft.temperature === null ? "" : String(draft.temperature)} data-testid="catalog-temperature"
            onChange={(event) => onDraft({ temperature: event.target.value === "" ? null : Number(event.target.value) })}>
            {choices.map((choice) => (
              <option key={choice.label} value={choice.value === null ? "" : String(choice.value)}>{choice.label}</option>
            ))}
          </select>
        </label>
        <label className="admin-panel__field">
          <span>Longest answer (tokens)</span>
          <input type="number" min={256} step={1} value={draft.maxOutputTokens} data-testid="catalog-max-output"
            onChange={(event) => onDraft({ maxOutputTokens: event.target.value })} />
        </label>
        <label className="admin-panel__field">
          <span>Context window (tokens)</span>
          <input type="number" min={1000} step={1} value={draft.contextLength} data-testid="catalog-context-length"
            disabled={row.provider.isGateway}
            onChange={(event) => onDraft({ contextLength: event.target.value })} />
        </label>
      </div>
      {row.provider.isGateway ? (
        <p className="model-catalog__sub">The context window of a gateway model comes from its gateway contract.</p>
      ) : (
        <p className="model-catalog__sub">
          Enter the window from the model's official documentation when the provider listing has none (Bedrock lists none).
        </p>
      )}
      <p className="model-catalog__sub">
        Applies wherever this model runs: chat, agents, workflows and the model gateway. Empty uses the platform default.
      </p>
    </div>
  );
}

const PRICE_FIELDS = [
  ["pricingInput", "Input / 1M (USD)"],
  ["pricingOutput", "Output / 1M (USD)"],
  ["pricingCacheRead", "Cache read / 1M (USD)"],
  ["pricingCacheWrite", "Cache write / 1M (USD)"],
] as const;

export function CostTab({ row, draft, onDraft }: TabProps) {
  const cacheRead = row.cost.pricingCacheRead === null ? "—" : `$${row.cost.pricingCacheRead.toFixed(2)}`;
  const [input, output] = priceText(row).split(" · ");
  const sourceLabel = row.cost.costSource && (COST_SOURCES as readonly string[]).includes(row.cost.costSource)
    ? COST_SOURCE_LABELS[row.cost.costSource as CostSource] : "Entered here";
  const priced = !row.provider.isGateway || draft.costSource === "catalog_pricing";
  return (
    <div className="admin-panel__stack">
      <div className="model-catalog__kv">
        <div><b>Input / 1M</b>{input || "—"}</div>
        <div><b>Output / 1M</b>{output || "—"}</div>
        <div><b>Cache read</b>{cacheRead}</div>
        <div><b>Source</b>{sourceLabel}</div>
      </div>
      {row.cost.editable ? (
        <>
          {row.provider.isGateway ? (
            <label className="admin-panel__field">
              <span>Cost source</span>
              <select value={draft.costSource} data-testid="catalog-cost-source"
                onChange={(event) => onDraft({ costSource: event.target.value as CostSource })}>
                {COST_SOURCES.map((source) => <option key={source} value={source}>{COST_SOURCE_LABELS[source]}</option>)}
              </select>
            </label>
          ) : null}
          {priced ? (
            <div className="admin-panel__form-grid">
              {PRICE_FIELDS.map(([key, label]) => (
                <label key={key} className="admin-panel__field">
                  <span>{label}</span>
                  <input type="number" min={0} step="any" value={draft[key]} data-testid={`catalog-${key}`}
                    onChange={(event) => onDraft({ [key]: event.target.value })} />
                </label>
              ))}
            </div>
          ) : (
            <label className="admin-panel__field">
              <span>Contract record</span>
              <input value={draft.contractReference} data-testid="catalog-contract-reference"
                onChange={(event) => onDraft({ contractReference: event.target.value })} />
            </label>
          )}
          <p className="model-catalog__sub">Cache prices are a pair: set both or neither.</p>
        </>
      ) : (
        <p className="model-catalog__sub">
          Prices from the provider's price list are read-only; the next sync would overwrite an edit.
        </p>
      )}
    </div>
  );
}
