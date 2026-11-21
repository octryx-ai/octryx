// The design-system switch (`toggle-switch`) as an accessible control: Space/Enter toggle it like a click.
export function CatalogSwitch({
  on,
  label,
  disabled = false,
  onChange,
  testId,
}: {
  on: boolean;
  label: string;
  disabled?: boolean;
  onChange: (next: boolean) => void;
  testId?: string;
}) {
  const toggle = () => {
    if (!disabled) onChange(!on);
  };
  return (
    <span
      className={`toggle-switch${on ? " toggle-switch--on" : ""}`}
      role="switch"
      aria-checked={on}
      aria-label={label}
      aria-disabled={disabled}
      tabIndex={disabled ? -1 : 0}
      data-testid={testId}
      onClick={(event) => {
        event.stopPropagation();
        toggle();
      }}
      onKeyDown={(event) => {
        if (event.key === " " || event.key === "Enter") {
          event.preventDefault();
          event.stopPropagation();
          toggle();
        }
      }}
    />
  );
}
