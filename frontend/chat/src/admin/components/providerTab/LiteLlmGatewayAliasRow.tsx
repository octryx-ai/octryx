import { LiteLlmGatewayApprovedFor } from "./LiteLlmGatewayApprovedFor";
import { costSourceLabel, gatewayCodeText, policyClassLabel } from "./litellmGatewayWords";
import { GATEWAY_CAPABILITIES, GATEWAY_COST_SOURCES, GATEWAY_DATA_POLICY_CLASSES } from "./litellmGatewayTypes";
import type { GatewayAliasDraft, GatewayCapability, GatewayCostSource, GatewayDataPolicyClass } from "./litellmGatewayTypes";

// One row of the Octryx alias catalog. An alias maps a name agents and
// users may request onto an upstream model group, and it carries the governed
// metadata the backend admission check demands.

const CAPABILITY_LABELS: Record<GatewayCapability, string> = {
  tools: "Tools",
  structured_output: "Structured output",
  reasoning: "Reasoning",
  vision: "Vision",
};

type LiteLlmGatewayAliasRowProps = {
  alias: GatewayAliasDraft;
  position: number;
  idPrefix: string;
  codes: string[];
  removable: boolean;
  disabled: boolean;
  onPatch: (patch: Partial<GatewayAliasDraft>) => void;
  onRemove: () => void;
};

function governedSummary(alias: GatewayAliasDraft): string {
  const level = policyClassLabel(alias.dataPolicyClass);
  const caps = GATEWAY_CAPABILITIES.filter((capability) => alias.capabilities[capability]).map(
    (capability) => CAPABILITY_LABELS[capability],
  );
  return `Cleared up to ${level} · ${caps.length ? caps.join(", ") : "no capabilities"}.`;
}

type AliasPartProps = {
  alias: GatewayAliasDraft;
  id: (suffix: string) => string;
  disabled: boolean;
  onPatch: (patch: Partial<GatewayAliasDraft>) => void;
};

function AliasBasicFields({ alias, id, disabled, onPatch }: AliasPartProps) {
  return (
    <div className="litellm-gateway__alias-grid">
      <label className="admin-panel__field" htmlFor={id("name")}>
        <span>Model name</span>
        <input
          id={id("name")}
          className="admin-panel__input"
          disabled={disabled}
          value={alias.alias}
          onChange={(e) => onPatch({ alias: e.target.value })}
        />
      </label>
      <label className="admin-panel__field" htmlFor={id("group")}>
        <span>Gateway model</span>
        <input
          id={id("group")}
          className="admin-panel__input"
          disabled={disabled}
          value={alias.modelGroup}
          onChange={(e) => onPatch({ modelGroup: e.target.value })}
        />
      </label>
      <label className="admin-panel__field" htmlFor={id("context")}>
        <span>Context limit</span>
        <input
          id={id("context")}
          className="admin-panel__input"
          disabled={disabled}
          value={alias.contextLimit}
          onChange={(e) => onPatch({ contextLimit: e.target.value })}
          inputMode="numeric"
        />
      </label>
      {alias.stored ? null : (
        <label className="admin-panel__field" htmlFor={id("policy")}>
          <span>Cleared up to</span>
          <select
            id={id("policy")}
            className="admin-panel__input"
            disabled={disabled}
            value={alias.dataPolicyClass}
            onChange={(e) => onPatch({ dataPolicyClass: e.target.value as GatewayDataPolicyClass })}
          >
            {GATEWAY_DATA_POLICY_CLASSES.map((policyClass) => (
              <option key={policyClass} value={policyClass}>
                {policyClassLabel(policyClass)}
              </option>
            ))}
          </select>
        </label>
      )}
    </div>
  );
}

function AliasCapabilities({ alias, id, disabled, onPatch }: AliasPartProps) {
  return (
    <fieldset className="litellm-gateway__capabilities">
      <legend className="litellm-gateway__legend-inline">
        Requested capabilities
      </legend>
      {GATEWAY_CAPABILITIES.map((capability) => (
        <label
          className="admin-panel__checkbox litellm-gateway__checkbox"
          key={capability}
          htmlFor={id(`cap-${capability}`)}
        >
          <input
            id={id(`cap-${capability}`)}
            type="checkbox"
            disabled={disabled}
            checked={alias.capabilities[capability]}
            onChange={(e) =>
              onPatch({ capabilities: { ...alias.capabilities, [capability]: e.target.checked } })
            }
          />
          {CAPABILITY_LABELS[capability]}
        </label>
      ))}
    </fieldset>
  );
}

function AliasCostInput({ alias, id, disabled, onPatch, suffix, label, field, inputMode }: AliasPartProps & {
  suffix: string;
  label: string;
  field: "inputPerMillionUsd" | "outputPerMillionUsd" | "contractReference";
  inputMode?: "decimal";
}) {
  return (
    <label className="admin-panel__field" htmlFor={id(suffix)}>
      <span>{label}</span>
      <input
        id={id(suffix)}
        className="admin-panel__input"
        disabled={disabled}
        value={alias.cost[field]}
        onChange={(e) => onPatch({ cost: { ...alias.cost, [field]: e.target.value } })}
        inputMode={inputMode}
      />
    </label>
  );
}

function AliasCostFields(props: AliasPartProps) {
  const { alias, id, disabled, onPatch } = props;
  return (
    <div className="litellm-gateway__alias-grid">
      <label className="admin-panel__field" htmlFor={id("cost-source")}>
        <span>Price</span>
        <select
          id={id("cost-source")}
          className="admin-panel__input"
          disabled={disabled}
          value={alias.cost.source}
          onChange={(e) => onPatch({ cost: { ...alias.cost, source: e.target.value as GatewayCostSource } })}
        >
          {GATEWAY_COST_SOURCES.map((source) => (
            <option key={source} value={source}>
              {costSourceLabel(source)}
            </option>
          ))}
        </select>
      </label>
      {alias.cost.source === "catalog_pricing" ? (
        <>
          <AliasCostInput {...props} suffix="cost-in" label="Input USD / 1M tokens" field="inputPerMillionUsd" inputMode="decimal" />
          <AliasCostInput {...props} suffix="cost-out" label="Output USD / 1M tokens" field="outputPerMillionUsd" inputMode="decimal" />
        </>
      ) : (
        <AliasCostInput {...props} suffix="cost-ref" label="Governance record" field="contractReference" />
      )}
    </div>
  );
}

export function LiteLlmGatewayAliasRow({
  alias,
  position,
  idPrefix,
  codes,
  removable,
  disabled,
  onPatch,
  onRemove,
}: LiteLlmGatewayAliasRowProps) {
  const id = (suffix: string) => `${idPrefix}-alias-${position}-${suffix}`;
  const part = { alias, id, disabled, onPatch };

  return (
    <div className="litellm-gateway__alias">
      <div className="litellm-gateway__alias-head">
        <span className="litellm-gateway__alias-title">
          {alias.alias.trim() || `Model ${position + 1}`}
        </span>
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={onRemove}
          disabled={disabled || !removable}
        >
          Remove
        </button>
      </div>
      <AliasBasicFields {...part} />
      {alias.stored ? (
        <p className="litellm-gateway__hint" data-testid="gateway-alias-governed">
          {governedSummary(alias)}
        </p>
      ) : (
        <>
          <AliasCapabilities {...part} />
          <LiteLlmGatewayApprovedFor
            selected={alias.approvedDataCategories ?? []}
            disabled={disabled}
            onChange={(approvedDataCategories) => onPatch({ approvedDataCategories })}
          />
          <AliasCostFields {...part} />
        </>
      )}
      {codes.length > 0 ? (
        <ul className="litellm-gateway__codes" aria-live="polite">
          {codes.map((code) => (
            <li key={code} title={code}>{gatewayCodeText(code)}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
