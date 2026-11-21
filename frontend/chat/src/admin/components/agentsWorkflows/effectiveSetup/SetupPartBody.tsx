// The body of one Effective setup part, by part id (backend `services/effective_setup/parts.py`).
import { Chip, ClassBadge } from "../awBadges";
import type { SetupPart } from "./effectiveSetupModel";

type Json = Record<string, unknown>;

const items = (value: unknown): Json[] =>
  Array.isArray(value) ? value.filter((item): item is Json => Boolean(item) && typeof item === "object") : [];
const names = (value: unknown): string[] => (Array.isArray(value) ? value.map(String) : []);
const text = (value: unknown): string => (typeof value === "string" ? value : value == null ? "" : String(value));

function SystemTexts({ details }: { details: Json }) {
  const keys = items(details.keys);
  if (!keys.length) return <div className="aw-sub aw-sub--flush">No platform text was rendered.</div>;
  return (
    <>
      <pre className="aw-code">
        {keys.map((key) => `${text(key.ref)}  ${key.overridden ? `override (${text(key.source)})` : "shipped"}`).join("\n")}
      </pre>
      {details.note ? <div className="aw-sub aw-sub--flush">{text(details.note)}</div> : null}
    </>
  );
}

function Agent({ details }: { details: Json }) {
  if (!details.selected) {
    return <div>No agent is selected: the turn runs without agent instructions.</div>;
  }
  return (
    <>
      <pre className="aw-code">{text(details.instructions) || "(no instructions)"}</pre>
      <div className="aw-sub aw-sub--flush">Resolution: {text(details.status)} · {text(details.mode)}</div>
    </>
  );
}

function Instructions({ details }: { details: Json }) {
  const loaded = items(details.items);
  if (!loaded.length) return <div>No instruction is loaded for this setup.</div>;
  return (
    <div className="aw-chips">
      {loaded.map((item) => (
        <Chip key={text(item.key)} tone="secondary">{`${text(item.key)} v${text(item.version)}`}</Chip>
      ))}
    </div>
  );
}

function Workflow({ details }: { details: Json }) {
  if (!details.selected) {
    return (
      <>
        <div className="aw-row">Class <ClassBadge value={details.capability_class} /></div>
        <div className="aw-sub aw-sub--flush">{text(details.note)}</div>
      </>
    );
  }
  const checks = items(details.checks);
  const policy = (details.tool_policy ?? {}) as Json;
  return (
    <>
      <div className="aw-row">Class <ClassBadge value={details.capability_class} /></div>
      {details.when_to_use ? <div>{text(details.when_to_use)}</div> : null}
      {checks.length ? (
        <div className="aw-steps">
          {checks.map((check, index) => (
            <div className="aw-row" key={`${text(check.type)}-${index}`}>
              <span className="aw-step__n">{index + 1}</span>
              <span className="aw-mono">{text(check.type)}</span>
              {text(check.description) ? <span className="aw-sub aw-sub--flush">{text(check.description)}</span> : null}
            </div>
          ))}
        </div>
      ) : null}
      {names(policy.allowlist).length ? (
        <div className="aw-chips">{names(policy.allowlist).map((name) => <Chip key={name} tone="secondary">{name}</Chip>)}</div>
      ) : null}
    </>
  );
}

function Skills({ details }: { details: Json }) {
  const skills = items(details.items);
  if (!skills.length) return <div>No skill is published for this Workspace.</div>;
  return (
    <>
      <div className="aw-chips">
        {skills.filter((skill) => skill.delivered).map((skill) => (
          <Chip key={text(skill.name)} tone="secondary">{`${text(skill.name)} v${text(skill.version)}`}</Chip>
        ))}
      </div>
      {skills.filter((skill) => !skill.delivered).map((skill) => (
        <div key={`withheld-${text(skill.name)}`}>
          <span className="aw-strike">{text(skill.name)}</span> <span className="aw-sub aw-sub--flush">{text(skill.reason)}</span>
        </div>
      ))}
      {details.delivery ? <div className="aw-sub aw-sub--flush">{text(details.delivery)}</div> : null}
    </>
  );
}

function Tools({ details }: { details: Json }) {
  const forbidden = items(details.forbidden);
  const native = names(details.native_gated);
  return (
    <>
      <div className="aw-chips">{names(details.offered).map((name) => <Chip key={name}>{name}</Chip>)}</div>
      {native.length ? (
        <div className="aw-sub aw-sub--flush">Claude Code tools checked by the PreToolUse hook: {native.join(", ")}</div>
      ) : null}
      {forbidden.length ? (
        <div className="aw-chips">
          {forbidden.map((item) => <Chip key={text(item.tool)} tone="danger">{`${text(item.tool)} — ${text(item.reason)}`}</Chip>)}
        </div>
      ) : null}
    </>
  );
}

function Approvals({ details }: { details: Json }) {
  const required = items(details.required);
  if (!required.length) return <div>No tool in this setup needs approval.</div>;
  return (
    <div className="aw-findings">
      {required.map((item) => (
        <div className="aw-finding" key={text(item.tool)}>
          <span className="aw-mono">{text(item.tool)}</span>
          <span>{text(item.reason)}</span>
        </div>
      ))}
    </div>
  );
}

export function SetupPartBody({ part }: { part: SetupPart }) {
  switch (part.id) {
    case "system_texts":
      return <SystemTexts details={part.details} />;
    case "agent":
      return <Agent details={part.details} />;
    case "instructions":
      return <Instructions details={part.details} />;
    case "workflow":
      return <Workflow details={part.details} />;
    case "skills":
      return <Skills details={part.details} />;
    case "tools":
      return <Tools details={part.details} />;
    case "approvals":
      return <Approvals details={part.details} />;
    default:
      return null;
  }
}
