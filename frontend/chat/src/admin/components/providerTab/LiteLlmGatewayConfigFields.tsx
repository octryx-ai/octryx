import { AdvancedSection, FormSection } from "../../../layout/FormSection";
import { LiteLlmGatewayAliasRow } from "./LiteLlmGatewayAliasRow";
import { GATEWAY_MAX_REQUEST_TIMEOUT_SECONDS, GATEWAY_MIN_REQUEST_TIMEOUT_SECONDS, GATEWAY_PROBE_MODEL_GROUP_FIELDS, GATEWAY_PROBE_PATHS, GATEWAY_PROBE_RESPONSE_SHAPES } from "./litellmGatewayTypes";
import { emptyGatewayAliasDraft } from "./litellmGatewayDrafts";
import { gatewayValidationCodes } from "./litellmGatewayValidation";
import type { GatewayAliasDraft, GatewayDraft, GatewayProbeModelGroupField, GatewayProbePath, GatewayProbeResponseShape } from "./litellmGatewayTypes";
import { gatewayCodeText, modelGroupFieldLabel, probePathLabel, responseShapeLabel } from "./litellmGatewayWords";

// Governed editor for the LiteLLM gateway fields the canonical Admin API
// accepts: endpoint_url plus config_json.litellm_gateway (host allowlist,
// pinned probe contract, request timeout, Octryx alias catalog).
// Design-system fields with labels, values in words, the probe contract under "Technical details";
// what each field means is in the Providers help (help/admin/providers.md).
//
// There is deliberately no key input of any kind. The virtual key is reachable
// only through LLMProvider.api_key_secret_ref, and the Admin API has no field
// for an existing secret reference, so this form cannot express it.

type LiteLlmGatewayConfigFieldsProps = {
  draft: GatewayDraft;
  onChange: (next: GatewayDraft) => void;
  idPrefix: string;
  disabled?: boolean;
};

type SectionProps = {
  draft: GatewayDraft;
  onChange: (next: GatewayDraft) => void;
  id: (suffix: string) => string;
  disabled: boolean;
};

function GatewayAddressSection({ draft, onChange, id, disabled }: SectionProps) {
  return (
    <FormSection title="Gateway">
      <label className="admin-panel__field" htmlFor={id("endpoint")}>
        <span>Address</span>
        <input
          id={id("endpoint")}
          className="admin-panel__input"
          value={draft.endpointUrl}
          disabled={disabled}
          onChange={(e) =>
            onChange({ ...draft, endpointUrl: e.target.value })
          }
          placeholder="https://litellm.internal.example/v1"
        />
      </label>
      <label className="admin-panel__field" htmlFor={id("allowlist")}>
        <span>Allowed hosts</span>
        <textarea
          id={id("allowlist")}
          className="admin-panel__input"
          rows={2}
          value={draft.hostAllowlist}
          disabled={disabled}
          onChange={(e) =>
            onChange({ ...draft, hostAllowlist: e.target.value })
          }
          placeholder="litellm.internal.example"
        />
      </label>
      <label className="admin-panel__field" htmlFor={id("timeout")}>
        <span>Timeout in seconds (optional)</span>
        <input
          id={id("timeout")}
          className="admin-panel__input litellm-gateway__short"
          value={draft.requestTimeoutSeconds}
          disabled={disabled}
          onChange={(e) =>
            onChange({ ...draft, requestTimeoutSeconds: e.target.value })
          }
          inputMode="numeric"
          placeholder={`${GATEWAY_MIN_REQUEST_TIMEOUT_SECONDS}–${GATEWAY_MAX_REQUEST_TIMEOUT_SECONDS}`}
        />
      </label>
    </FormSection>
  );
}

function GatewayModelsSection({ draft, onChange, idPrefix, disabled, codesByAlias }: Omit<SectionProps, "id"> & {
  idPrefix: string;
  codesByAlias: Map<number, string[]>;
}) {
  const patchAlias = (index: number, patch: Partial<GatewayAliasDraft>) => {
    onChange({
      ...draft,
      aliases: draft.aliases.map((alias, position) =>
        position === index ? { ...alias, ...patch } : alias,
      ),
    });
  };

  return (
    <FormSection title="Models">
      {draft.aliases.map((alias, index) => (
        <LiteLlmGatewayAliasRow
          key={index}
          alias={alias}
          position={index}
          idPrefix={idPrefix}
          codes={codesByAlias.get(index) ?? []}
          removable={draft.aliases.length > 1}
          disabled={disabled}
          onPatch={(patch) => patchAlias(index, patch)}
          onRemove={() =>
            onChange({
              ...draft,
              aliases: draft.aliases.filter(
                (_, position) => position !== index,
              ),
            })
          }
        />
      ))}
      <div>
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={() =>
            onChange({
              ...draft,
              aliases: [...draft.aliases, emptyGatewayAliasDraft()],
            })
          }
          disabled={disabled}
        >
          Add model
        </button>
      </div>
    </FormSection>
  );
}

// One probe-contract choice: a select over fixed values, shown in words.
function ProbeSelect<T extends string>({ selectId, label, value, values, labelOf, disabled, onSelect }: {
  selectId: string;
  label: string;
  value: T;
  values: readonly T[];
  labelOf: (value: T) => string;
  disabled: boolean;
  onSelect: (value: T) => void;
}) {
  return (
    <label className="admin-panel__field" htmlFor={selectId}>
      <span>{label}</span>
      <select
        id={selectId}
        className="admin-panel__input"
        value={value}
        disabled={disabled}
        onChange={(e) => onSelect(e.target.value as T)}
      >
        {values.map((item) => (
          <option key={item} value={item}>
            {labelOf(item)}
          </option>
        ))}
      </select>
    </label>
  );
}

function GatewayTechnicalSection({ draft, onChange, id, disabled }: SectionProps) {
  return (
    <AdvancedSection label="Technical details" testId="litellm-gateway-technical">
      <ProbeSelect<GatewayProbePath>
        selectId={id("probe-path")}
        label="Models path"
        value={draft.probeModelsPath}
        values={GATEWAY_PROBE_PATHS}
        labelOf={probePathLabel}
        disabled={disabled}
        onSelect={(probeModelsPath) => onChange({ ...draft, probeModelsPath })}
      />
      <ProbeSelect<GatewayProbeResponseShape>
        selectId={id("probe-shape")}
        label="Response format"
        value={draft.probeResponseShape}
        values={GATEWAY_PROBE_RESPONSE_SHAPES}
        labelOf={responseShapeLabel}
        disabled={disabled}
        onSelect={(probeResponseShape) => onChange({ ...draft, probeResponseShape })}
      />
      <ProbeSelect<GatewayProbeModelGroupField>
        selectId={id("probe-field")}
        label="Model name field"
        value={draft.probeModelGroupField}
        values={GATEWAY_PROBE_MODEL_GROUP_FIELDS}
        labelOf={modelGroupFieldLabel}
        disabled={disabled}
        onSelect={(probeModelGroupField) => onChange({ ...draft, probeModelGroupField })}
      />
    </AdvancedSection>
  );
}

export function LiteLlmGatewayConfigFields({
  draft,
  onChange,
  idPrefix,
  disabled = false,
}: LiteLlmGatewayConfigFieldsProps) {
  const validation = gatewayValidationCodes(draft);
  const codesByAlias = new Map(
    validation.aliases.map((entry) => [entry.index, entry.codes]),
  );
  const id = (suffix: string) => `${idPrefix}-${suffix}`;

  return (
    <div className="litellm-gateway">
      <GatewayAddressSection draft={draft} onChange={onChange} id={id} disabled={disabled} />

      <GatewayModelsSection draft={draft} onChange={onChange} idPrefix={idPrefix} disabled={disabled} codesByAlias={codesByAlias} />

      <GatewayTechnicalSection draft={draft} onChange={onChange} id={id} disabled={disabled} />

      {validation.form.length > 0 ? (
        <ul className="litellm-gateway__codes" aria-live="polite" data-testid="litellm-gateway-problems">
          {validation.form.map((code) => (
            <li key={code} title={code}>{gatewayCodeText(code)}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
