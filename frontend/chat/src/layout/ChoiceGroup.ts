import { createElement, type KeyboardEvent, type ReactNode } from "react";

// A choice between a few values (Light | Dark, Desktop | Phone, OK | Change): the look of SegmentedTabs small, but
// a group of toggle buttons (aria-pressed), not tabs — tabs switch panels, a choice sets a value (
// Spec Studio). Arrow keys move the choice like in a radio group.

export type Choice = { key: string; label: string; icon?: ReactNode; disabled?: boolean; testId?: string };

export type ChoiceGroupProps = {
  choices: Choice[];
  value: string;
  onChange: (key: string) => void;
  // Accessible name of the group ("Theme").
  label: string;
  size?: "regular" | "small";
  testId?: string;
};

/** The choice an arrow key moves to (wrapping, skipping disabled ones), or null for any other key. Pure. */
export function nextChoice(choices: Choice[], current: string, key: string): string | null {
  const enabled = choices.filter((choice) => !choice.disabled);
  if (!enabled.length) return null;
  const index = Math.max(0, enabled.findIndex((choice) => choice.key === current));
  if (key === "ArrowRight" || key === "ArrowDown") return enabled[(index + 1) % enabled.length].key;
  if (key === "ArrowLeft" || key === "ArrowUp") return enabled[(index - 1 + enabled.length) % enabled.length].key;
  return null;
}

export function ChoiceGroup({ choices, value, onChange, label, size = "small", testId }: ChoiceGroupProps) {
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const next = nextChoice(choices, value, event.key);
    if (!next || next === value) return;
    event.preventDefault();
    onChange(next);
  };
  return createElement(
    "div",
    { className: `ds-segments ds-segments--${size} ds-choice`, role: "group", "aria-label": label, onKeyDown, "data-testid": testId },
    ...choices.map((choice) => {
      const selected = choice.key === value;
      return createElement(
        "button",
        {
          key: choice.key,
          type: "button",
          "aria-pressed": selected,
          disabled: choice.disabled,
          className: `ds-segments__tab${selected ? " is-selected" : ""}`,
          "data-testid": choice.testId,
          onClick: () => onChange(choice.key),
        },
        choice.icon ?? null,
        choice.label,
      );
    }),
  );
}
