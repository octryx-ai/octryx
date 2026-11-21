import { deviationPointText, lockLabel } from "../../admin/components/corpIdentity/corpStudioLocksModel";
import { StatusLabel } from "../../layout/StatusLabel";
import { SaveLine } from "./SaveLine";
import { StudioIcon } from "./specStudioIcons";
import { approveState, changeCount, contrastRows, type StudioPayload } from "./specStudioModel";
import type { SpecStudioHandle } from "./useSpecStudio";

// Approve: freezes the spec and the mock as version n (the review baseline every story is compared against) and
// writes every decision into SPEC.md. Open points block it; the product owner's own changes go to revision first.

export function StudioApprove({ payload, studio, onShowPoint }: { payload: StudioPayload; studio: SpecStudioHandle;
  onShowPoint: (section: string) => void }) {
  const state = approveState(payload);
  const contrastOk = contrastRows(payload.design).every((row) => row.passes);
  const rejected = Object.values(payload.state.acceptance ?? {}).filter((v) => v.verdict === "change").length;
  const notes = (payload.state.comments ?? []).filter((c) => c.text.trim()).length;
  const latest = payload.approved.at(-1);
  // Only reasons for deviations from the Corporate Identity are open: the product owner gives them, no revision.
  const onlyYours = payload.open_points.length > 0 && payload.open_points.every((point) => point.by === "product_owner");
  return (
    <div className="studio-stack">
      <div className="studio-kpis">
        <div className="ds-kpi"><span className="ds-kpi__value">{changeCount(payload.state)}</span><span className="ds-kpi__label">Decisions you changed</span></div>
        <div className="ds-kpi"><span className="ds-kpi__value">{notes}</span><span className="ds-kpi__label">Notes on the mock</span></div>
        <div className="ds-kpi"><span className="ds-kpi__value">{rejected}</span><span className="ds-kpi__label">Criteria to change</span></div>
        <div className="ds-kpi"><span className="ds-kpi__value">{payload.open_points.length}</span><span className="ds-kpi__label">Open points</span></div>
        <div className="ds-kpi"><span className="ds-kpi__value"><StudioIcon name={contrastOk ? "check" : "x"} size={20} /></span><span className="ds-kpi__label">Contrast AA light and dark</span></div>
      </div>
      {payload.open_points.length ? (
        <ul className="studio-points">
          {payload.open_points.map((point, index) => (
            <li key={index}>
              <StatusLabel tone="attention" label={point.section} />
              <span>{deviationPointText(point.target, point.text)}</span>
              <button type="button" className="ds-btn ds-btn--ghost ds-btn--sm" onClick={() => onShowPoint(point.section)}>Show</button>
            </li>
          ))}
        </ul>
      ) : null}
      {payload.corporate && (payload.deviations ?? []).length ? (
        <div className="studio-control">
          <span className="studio-label">Deviations from Corporate: {payload.corporate.profile_name}</span>
          <ul className="studio-deviations">
            {(payload.deviations ?? []).map((deviation) => (
              <li key={deviation.path} className="studio-deviation">
                <span className="studio-deviation__diff">{lockLabel(deviation.path)}: {deviation.chosen} instead of {deviation.corporate}</span>
                {deviation.reason ? <span>{deviation.reason}</span> : <StatusLabel tone="attention" label="Reason required" />}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {state.mode === "frozen" && latest ? (
        <p className="studio-frozen" role="status"><StudioIcon name="lock" /> Version {latest.version} approved by {latest.who} on {new Date(latest.at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}: {latest.decisions.length} decisions written into SPEC.md, the mock is the review baseline.</p>
      ) : (
        <div className="studio-approve">
          {state.mode === "revise" || (state.mode === "blocked" && !onlyYours) ? (
            <button type="button" className="ds-btn ds-btn--primary" disabled={!payload.awaiting_approval} onClick={() => void studio.decide("revise")}>
              Send to revision
            </button>
          ) : (
            <button type="button" className="ds-btn ds-btn--primary" disabled={state.mode !== "approve"} onClick={() => void studio.decide("approve")}>
              Approve spec v{payload.approved.length + 1} and start the stories
            </button>
          )}
          <span className="studio-hint">{state.reason}</span>
        </div>
      )}
      <SaveLine save={studio.saves.approve} />
      <details className="studio-log">
        <summary>What is written into SPEC.md</summary>
        <pre>{JSON.stringify({ design: payload.design, answers: payload.state.answers ?? {}, comments: (payload.state.comments ?? []).map((c) => ({ screen: c.screen, element: c.element, text: c.text })) }, null, 2)}</pre>
      </details>
    </div>
  );
}
