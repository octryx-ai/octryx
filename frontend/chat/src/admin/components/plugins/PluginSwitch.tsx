// On / Off of one plugin in a Workspace: a real switch for who may change it, else the state as plain text. While the
// call runs it stays pressed in its new position and refuses further clicks (aria-busy).
export function PluginSwitch({ on, label, busy, editable, onToggle, testId }: {
  on: boolean;
  // What is switched, for screen readers ("Release notes").
  label: string;
  busy: boolean;
  editable: boolean;
  onToggle: () => void;
  testId?: string;
}) {
  const state = on ? "On" : "Off";
  if (!editable) return <span className="plg-switch-state" data-testid={testId ? `${testId}-state` : undefined}>{state}</span>;
  return (
    <span className="plg-switch-wrap">
      <span className="plg-switch-state" aria-hidden="true">{busy ? (on ? "Switching on…" : "Switching off…") : state}</span>
      <button type="button" role="switch" aria-checked={on} aria-busy={busy || undefined} aria-label={`${label}: ${state}`}
        className={`plg-switch${on ? " is-on" : ""}${busy ? " is-busy" : ""}`} data-testid={testId}
        onClick={() => { if (!busy) onToggle(); }} />
    </span>
  );
}
