import { useEffect, useState } from "react";

import { readJson } from "../../utils/adminPanelHelpers";
import {
  readContentCategories,
  toggleCategory,
} from "./litellmGatewayApprovedCategories";
import type { ContentCategory } from "./litellmGatewayApprovedCategories";

// "Approved for sensitive data" on one alias: one chip per content
// category the policy engine knows (built-in + admin categories of the working
// policy set). Saved with the alias catalog, so the provider update audit
// records the change.

const CATEGORIES_PATH = "/api/v1/admin/policy-engine/content-detectors";
let categoriesRequest: Promise<ContentCategory[]> | null = null;

function loadCategories(): Promise<ContentCategory[]> {
  categoriesRequest ??= readJson<unknown>(CATEGORIES_PATH)
    .then(readContentCategories)
    .catch((error) => {
      categoriesRequest = null;
      throw error;
    });
  return categoriesRequest;
}

export function LiteLlmGatewayApprovedFor({
  selected,
  disabled,
  onChange,
}: {
  selected: string[];
  disabled: boolean;
  onChange: (next: string[]) => void;
}) {
  const [categories, setCategories] = useState<ContentCategory[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    void loadCategories()
      .then((list) => {
        if (alive) setCategories(list);
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  const known = categories ?? [];
  const options = [
    ...known,
    ...selected
      .filter((id) => !known.some((item) => item.id === id))
      .map((id) => ({ id, label: id })),
  ];

  return (
    <fieldset className="litellm-gateway__capabilities">
      <legend className="litellm-gateway__legend-inline">
        Approved for sensitive data
      </legend>
      <div className="admin-policy-chip-list" data-testid="alias-approved-for">
        {options.map((item) => {
          const on = selected.includes(item.id);
          return (
            <button
              key={item.id}
              type="button"
              aria-pressed={on}
              disabled={disabled}
              className={`admin-policy-chip litellm-gateway__chip${on ? "" : " admin-policy-chip--secondary"}`}
              onClick={() => onChange(toggleCategory(selected, item.id))}
            >
              {on ? "" : "+ "}
              {item.label} ({item.id})
            </button>
          );
        })}
        {!options.length ? (
          <span className="litellm-gateway__hint">
            {failed
              ? "The content categories could not be loaded (platform admin role required)."
              : "Loading the content categories…"}
          </span>
        ) : null}
      </div>
    </fieldset>
  );
}
