import type { StudioPayload } from "./specStudioModel";

// Overview: what the product is, the stories, what is out, the flow, the glossary and the zero-config requirements.
export function StudioOverview({ payload }: { payload: StudioPayload }) {
  const { artefact } = payload;
  return (
    <div className="studio-stack">
      {artefact.summary ? <p className="studio-lead">{artefact.summary}</p> : null}
      {artefact.mode === "feature" ? <p className="studio-hint">A feature on an approved app: only its new screens, questions and rules are shown; the app's existing screens are context.</p> : null}
      <div className="studio-grid">
        {artefact.stories.map((story) => (
          <div key={story.title} className="ds-card"><h3 className="ds-card__title">{story.title}</h3><p className="ds-card__meta">{story.summary}</p></div>
        ))}
      </div>
      {artefact.out_of_scope.length ? <p className="studio-hint">Not included: {artefact.out_of_scope.join(", ")}.</p> : null}
      {artefact.flow.progressive_disclosure ? <p><strong>Flow.</strong> {artefact.flow.progressive_disclosure} {artefact.flow.carry_over}</p> : null}
      {artefact.requirements.length ? (
        <div className="ds-card">
          <h3 className="ds-card__title">Works without setup?</h3>
          <ul className="studio-list">
            {artefact.requirements.map((item) => (
              <li key={item.id}><code className="studio-code">{item.id}</code> {item.text}: <strong>{item.zero_config === "yes" ? "yes" : "no"}</strong>, {item.how}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {artefact.glossary.length ? (
        <div className="ds-card">
          <h3 className="ds-card__title">Words</h3>
          <ul className="studio-list">
            {artefact.glossary.map((entry) => (
              <li key={entry.term}><strong>{entry.term}</strong> / {entry.translation}{entry.avoid.length ? `, not: ${entry.avoid.join(", ")}` : ""}</li>
            ))}
            {artefact.conditions.map((entry) => <li key={entry.word}><strong>{entry.word}</strong>: {entry.definition}</li>)}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
