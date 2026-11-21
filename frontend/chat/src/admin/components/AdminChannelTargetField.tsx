import { TEAMS_TARGET_EXAMPLES, describeTeamsTarget } from "./channelDeliveryTarget";

type AdminChannelTargetFieldProps = {
  target: string;
  setTarget: (value: string) => void;
};

// The Teams target stays one pipe-separated value (the stored format); the
// field explains both formats with an example and names each recognised part.
export function AdminChannelTargetField({ target, setTarget }: AdminChannelTargetFieldProps) {
  const description = describeTeamsTarget(target);
  return (
    <div className="admin-form-field admin-form-grid__full">
      <label className="admin-form-field__label" htmlFor="delivery-target-value">
        Teams target
      </label>
      <input
        id="delivery-target-value"
        value={target}
        onChange={(event) => setTarget(event.target.value)}
        placeholder={TEAMS_TARGET_EXAMPLES[1].format}
        spellCheck={false}
        aria-describedby="delivery-target-formats"
      />
      <div className="admin-form-help" id="delivery-target-formats">
        Use one of two formats, parts separated by <code>|</code>:
        <ul className="admin-channels__formats">
          {TEAMS_TARGET_EXAMPLES.map((example) => (
            <li key={example.format}>
              <strong>{example.kind}:</strong> <code>{example.format}</code>
              <div className="admin-channels__example">
                Example: <code>{example.example}</code>
              </div>
            </li>
          ))}
        </ul>
        The service URL and IDs come from the Teams bot conversation or channel
        link.
      </div>
      {description.state === "valid" ? (
        <dl className="admin-channels__parts" aria-label="Recognised target parts">
          <div>
            <dt>Type</dt>
            <dd>{description.kind}</dd>
          </div>
          {description.parts.map((part) => (
            <div key={part.label}>
              <dt>{part.label}</dt>
              <dd>
                <code>{part.value}</code>
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
      {description.state === "invalid" ? (
        <span className="admin-panel__form-error" role="alert">
          {description.message}
        </span>
      ) : null}
    </div>
  );
}
