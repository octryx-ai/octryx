import { useState } from "react";

import { SidePanel } from "../../layout/SidePanel";
import "./runTokens.css";

import { useRunResource } from "./useRunResource";
import {
  BASIS_TEXT,
  consumerText,
  phaseBars,
  phaseFacts,
  tokenCount,
  tokenProfilePath,
  totalsText,
  type TokenProfile,
} from "./runTokensModel";

type Props = { runId: string; refreshKey: unknown };

// Where the run's tokens went: folded away like the run's details; read only when opened.
export function RunTokens({ runId, refreshKey }: Props) {
  const [open, setOpen] = useState(false);
  const profile = useRunResource<TokenProfile>(open ? tokenProfilePath(runId) : null, refreshKey);
  return (
    <details
      className="run-tokens"
      data-testid="workflow-run-tokens"
      onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}
    >
      <summary>Tokens</summary>
      {open && !profile ? <p className="ds-empty">Reading the run's tokens…</p> : null}
      {profile ? <RunTokensBody profile={profile} /> : null}
    </details>
  );
}

export function RunTokensBody({ profile }: { profile: TokenProfile }) {
  if (!profile.phases.length) {
    return <p className="ds-empty">No model calls on a device yet.</p>;
  }
  const bars = phaseBars(profile);
  return (
    <div className="run-tokens__body">
      <p className="run-tokens__meta" data-testid="run-tokens-basis">
        {totalsText(profile)}. {BASIS_TEXT[profile.basis]}
      </p>
      <ul className="run-tokens__legend" aria-label="Categories">
        {profile.categories.map((category) => (
          <li key={category.key}>
            <span className={`run-tokens__swatch run-tokens__part--${category.key}`} aria-hidden="true" />
            {category.label}
          </li>
        ))}
      </ul>
      <ol className="run-tokens__phases" aria-label="Tokens per phase">
        {bars.map(({ phase, total, width, segments }) => (
          <li key={phase.phase} className="run-tokens__phase" data-testid="run-tokens-phase">
            <div className="run-tokens__phase-head">
              <span className="run-tokens__phase-name">{phase.phase}</span>
              <span className="run-tokens__phase-total">{tokenCount(total)}</span>
            </div>
            <div
              className="run-tokens__bar"
              style={{ width: `${Math.max(width * 100, 2)}%` }}
              role="img"
              aria-label={segments.map((segment) => `${segment.label} ${tokenCount(segment.tokens)}`).join(", ")}
            >
              {segments.map((segment) => (
                <span
                  key={segment.key}
                  className={`run-tokens__part run-tokens__part--${segment.key}`}
                  style={{ width: `${segment.share * 100}%` }}
                  title={`${segment.label}: ${tokenCount(segment.tokens)}`}
                />
              ))}
            </div>
            <div className="run-tokens__phase-meta">{phaseFacts(phase)}</div>
          </li>
        ))}
      </ol>
      {profile.consumers.length ? (
        <section className="run-tokens__section">
          <h4 className="run-tokens__title">Top consumers</h4>
          <ol className="run-tokens__list" data-testid="run-tokens-consumers">
            {profile.consumers.map((consumer) => (
              <li key={`${consumer.tool}:${consumer.label}`}>
                <span className="run-tokens__label" title={consumer.label}>{consumer.label}</span>
                <span className="run-tokens__value">{consumerText(consumer)}</span>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
      {profile.hints.length ? (
        <section className="run-tokens__section">
          <h4 className="run-tokens__title">Where to save</h4>
          <ul className="run-tokens__list run-tokens__hints" data-testid="run-tokens-hints">
            {profile.hints.map((hint) => (
              <li key={`${hint.rule}:${hint.text}`} data-rule={hint.rule}>
                <span className="run-tokens__label">{hint.text}</span>
                {hint.tokens ? <span className="run-tokens__value">{tokenCount(hint.tokens)} tokens</span> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

// The same view in a side panel: a Workspace member with read access to the run (team lead,
// Workspace admin) sees where its tokens went from Work › Runs, without the run's chat, which only its owner opens.
export function RunTokensPanel({ runId, title, onClose }: { runId: string; title: string; onClose: () => void }) {
  const profile = useRunResource<TokenProfile>(tokenProfilePath(runId), runId);
  return (
    <SidePanel title="Tokens" subtitle={title} onClose={onClose} testId="run-tokens-panel">
      {profile ? <RunTokensBody profile={profile} /> : <p className="ds-empty">Reading the run's tokens…</p>}
    </SidePanel>
  );
}
