import { createElement, useEffect, useState, type ReactNode } from "react";

// One colour token: picker, name and #RRGGBB field (Spec Studio Design, the Corporate Identity page). Agreed with
// In src/layout next to ChoiceGroup. A value can carry where it comes from ("Corporate",
// "derived") and be locked: then it is read-only and says why.

/** "#rrggbb" (with or without #, 3 or 6 digits) as "#RRGGBB", or null when it is no colour. Pure. */
export function normalizeHex(input: string): string | null {
  const raw = input.trim().replace(/^#/, "");
  if (/^[0-9a-fA-F]{3}$/.test(raw)) return `#${raw.split("").map((c) => c + c).join("").toUpperCase()}`;
  return /^[0-9a-fA-F]{6}$/.test(raw) ? `#${raw.toUpperCase()}` : null;
}

export type ColorRowProps = {
  name: string;
  label: string;
  value: string;
  disabled: boolean;
  onSave: (hex: string) => void;
  // "Corporate" or "derived": shown as a small tag after the name.
  source?: string | null;
  // Locked by the Corporate Identity: read-only, with this icon and the reason as its title.
  locked?: { icon: ReactNode; reason: string } | null;
};

export function ColorRow({ name, label, value, disabled, onSave, source, locked }: ColorRowProps) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const hex = normalizeHex(draft);
  const off = disabled || Boolean(locked);
  const commit = () => { if (hex && hex !== value) onSave(hex); else if (!hex) setDraft(value); };
  return createElement(
    "label",
    { className: `studio-color${locked ? " is-locked" : ""}`, title: locked?.reason },
    createElement("input", {
      type: "color", className: "studio-color__swatch", value: (hex ?? value).toLowerCase(), disabled: off,
      "aria-label": `${label} colour picker`, onChange: (event: { target: { value: string } }) => setDraft(event.target.value.toUpperCase()),
      onBlur: commit,
    }),
    createElement(
      "span",
      { className: "studio-color__name" },
      label,
      source ? createElement("span", { className: "studio-color__source" }, source) : null,
      locked ? createElement("span", { className: "studio-color__lock", "aria-label": locked.reason }, locked.icon) : null,
    ),
    createElement("input", {
      type: "text", className: "admin-panel__input ds-input studio-color__hex", value: draft, disabled: off, spellCheck: false,
      "aria-label": `${label} (${name}) as #RRGGBB`, "aria-invalid": !hex,
      onChange: (event: { target: { value: string } }) => setDraft(event.target.value), onBlur: commit,
      onKeyDown: (event: { key: string }) => { if (event.key === "Enter") commit(); },
    }),
  );
}
