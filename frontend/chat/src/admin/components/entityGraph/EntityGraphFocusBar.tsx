import { contextLabel, crumbLabel, type GraphContext } from "./entityGraphFocusTrail";

// The focus trail as breadcrumbs: every earlier context (the whole view, a search, a neighbourhood) is one step
// back; the last crumb is where the reader is. Shown once there is somewhere to go back to.
export function EntityGraphFocusBar({ current, trail, onBack }: {
  current: GraphContext; trail: GraphContext[]; onBack: (index: number) => void;
}) {
  if (!trail.length) return null;
  return <nav className="kg-trail" aria-label="Graph focus trail">
    <ol>
      {trail.map((context, index) => <li key={index}>
        <button type="button" className="kg-trail__crumb" title={`Back to ${contextLabel(context)}`} onClick={() => onBack(index)}>
          {crumbLabel(context)}</button>
        <span className="kg-trail__sep" aria-hidden="true">›</span>
      </li>)}
      <li><span className="kg-trail__current" aria-current="location">{crumbLabel(current)}</span></li>
    </ol>
  </nav>;
}
