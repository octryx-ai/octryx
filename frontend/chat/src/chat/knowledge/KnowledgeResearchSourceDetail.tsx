import { SidePanel } from "../../layout/SidePanel";
import type { ResearchAction, ResearchActionKey, ResearchSourceRow } from "./researchSourceRows";

const ACTION_TONES: Record<ResearchAction["tone"], string> = {
  primary: " admin-panel__action-btn--primary",
  danger: " admin-panel__action-btn--danger",
  default: "",
};

// One research website in the side panel over the list: its reason, where research found it, where it applies,
// and the decisions (Remove, Block, Approve; the bright one last). A website the person may not decide shows why.
export function KnowledgeResearchSourceDetail({ row, busy, onDecide, onClose }: {
  row: ResearchSourceRow;
  busy: boolean;
  onDecide: (key: ResearchActionKey) => void;
  onClose: () => void;
}) {
  const ordered = [...row.actions].sort((a, b) => (a.tone === "primary" ? 1 : 0) - (b.tone === "primary" ? 1 : 0));
  return (
    <SidePanel title={row.pattern} subtitle={row.stateLabel} onClose={onClose} testId="research-website-panel"
      footer={ordered.length ? (
        <>
          {ordered.map((action) => <button key={action.key} type="button" disabled={busy}
            className={`admin-panel__action-btn${ACTION_TONES[action.tone]}`} aria-label={`${action.label} ${row.pattern}`}
            data-testid={`research-website-${action.key}`} onClick={() => onDecide(action.key)}>{action.label}</button>)}
        </>
      ) : <span className="admin-panel__cell--muted" data-testid="research-website-readonly">{row.readOnlyNote}</span>}>
      <dl className="knowledge-research__meta knowledge-research__meta--panel">
        <div><dt>Reason</dt><dd>{row.reason}</dd></div>
        {row.meta.map((item) => <div key={item.label}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}
        {row.evidenceUrl ? <div><dt>Found at</dt><dd>
          <a href={row.evidenceUrl} target="_blank" rel="noopener noreferrer">Where research found it</a></dd></div> : null}
      </dl>
    </SidePanel>
  );
}
