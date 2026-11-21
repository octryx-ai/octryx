import { useEffect, useState } from "react";

import { StatusLabel } from "../../layout/StatusLabel";
import { SaveLine } from "./SaveLine";
import type { Rule, StudioPayload } from "./specStudioModel";
import type { SpecStudioHandle } from "./useSpecStudio";

// Rules with their worked examples: exactly these examples become tests (Bench Coffee lesson 3: one realistic example
// per numeric rule). A changed value sends the spec back to the spec phase, which recomputes the examples.

function ParamField({ rule, param, value, frozen, studio }: { rule: Rule; param: Rule["params"][number]; value: string;
  frozen: boolean; studio: SpecStudioHandle }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const key = `rule:${rule.id}.${param.id}`;
  const send = () => {
    studio.markDirty(key, false);
    if (draft.trim() && draft.trim() !== value) void studio.save("rules", { op: "rule", rule: rule.id, param: param.id, value: draft.trim() });
  };
  return (
    <label className="studio-param">
      <span>{param.label}</span>
      <input type="text" inputMode="decimal" className="admin-panel__input ds-input studio-param__value" value={draft} disabled={frozen}
        onChange={(event) => { setDraft(event.target.value); studio.markDirty(key, event.target.value !== value); }}
        onBlur={send} onKeyDown={(event) => { if (event.key === "Enter") send(); }} />
      {param.unit ? <span className="studio-hint">{param.unit}</span> : null}
    </label>
  );
}

export function StudioRules({ payload, studio }: { payload: StudioPayload; studio: SpecStudioHandle }) {
  const changed = payload.state.rules ?? {};
  return (
    <div className="studio-grid">
      {payload.artefact.rules.map((rule) => (
        <div key={rule.id} className="ds-card studio-rule">
          <h3 className="ds-card__title">{rule.id} {rule.title}{rule.identifier ? <code className="studio-code">{rule.identifier}</code> : null}</h3>
          <p className="studio-rule__text">{rule.text}</p>
          {rule.params.length ? (
            <div className="studio-params">
              {rule.params.map((param) => (
                <ParamField key={param.id} rule={rule} param={param} value={changed[rule.id]?.[param.id] ?? param.value}
                  frozen={payload.frozen} studio={studio} />
              ))}
            </div>
          ) : null}
          {changed[rule.id] ? <StatusLabel tone="attention" label="Changed: the example is recomputed on revision" /> : null}
          <ul className="studio-examples">
            {rule.examples.map((example, index) => (
              <li key={index} className="studio-example">
                <span>{example.given}</span><span aria-hidden="true">→</span><strong>{example.expect}</strong>
                {example.realistic ? <StatusLabel tone="success" label="Realistic" /> : null}
              </li>
            ))}
          </ul>
        </div>
      ))}
      <SaveLine save={studio.saves.rules} />
    </div>
  );
}
