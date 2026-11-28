import { useEffect, useState } from "react";

import { readJson } from "../../utils/adminPanelHelpers";

type Policy = "block" | "warn";
const PATH = "/api/v1/admin/runtime/unpriced-model-policy";
const OPTIONS: Array<[Policy, string, string]> = [
  ["block", "Refuse the run", "While a cost cap is active, a platform-billed model without a price is refused before it is called, until its price is set in Runtime → Model catalog."],
  ["warn", "Run and warn", "The model runs; Observability shows its usage as unpriced. Cost caps cannot stop it, because its cost counts as $0."],
];

// A cost cap is estimated from the model's price, so it cannot stop an unpriced model.
export function UnpricedModelPolicyField() {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    readJson<{ policy: Policy }>(PATH)
      .then((payload) => active && setPolicy(payload.policy))
      .catch(() => active && setMessage("The setting could not be loaded."));
    return () => {
      active = false;
    };
  }, []);

  const save = async (next: Policy) => {
    setPolicy(next);
    try {
      const saved = await readJson<{ policy: Policy }>(PATH, { method: "PUT", body: JSON.stringify({ policy: next }) });
      setPolicy(saved.policy);
      setMessage("Saved.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The setting could not be saved.");
    }
  };

  return (
    <fieldset className="admin-panel__card" disabled={policy === null} data-testid="unpriced-model-policy">
      <legend className="admin-panel__section-header">Models without a price</legend>
      <div role="radiogroup" aria-label="Models without a price">
        {OPTIONS.map(([value, title, help]) => (
          <label key={value} className="admin-option-card">
            <input type="radio" name="unpriced-model-policy" value={value} checked={policy === value}
              onChange={() => void save(value)} />
            <span className="admin-option-card__body">
              <span className="admin-option-card__title">{title}</span>
              <span className="admin-option-card__desc">{help}</span>
            </span>
          </label>
        ))}
      </div>
      {message ? <p className="admin-panel__hint" role="status">{message}</p> : null}
    </fieldset>
  );
}
