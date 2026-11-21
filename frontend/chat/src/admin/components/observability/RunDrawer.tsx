import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import { formatTime } from "./obFormat";
import { RunDecisionsAndCost, RunFacts, RunSetupAndContent, RunSteps } from "./RunDrawerParts";
import { sessionLink, type RunRow } from "./runsModel";
import { useRunDetail } from "./useRunDetail";

type Props = {
  runKey: string;
  // The list row when opened from Runs; from elsewhere (a decision) the drawer reads everything from the detail.
  row?: RunRow;
  readJson: ReadJsonFn;
  onClose: () => void;
};

// Run drawer: steps, tool calls, cost and effective setup without content; content is an audited admin read.
export function RunDrawer({ runKey, row, readJson, onClose }: Props) {
  const { detail, error, content, showSetup, setShowSetup, showContent } = useRunDetail(readJson, runKey);
  const chatHref = sessionLink(detail);
  const footer = (
    <>
      {chatHref ? (
        <a className="admin-panel__action-btn" href={chatHref}>Open session</a>
      ) : detail?.session_id ? (
        <span className="ob-muted" title="A chat opens only for the user who owns it.">Owner only</span>
      ) : null}
      <button
        type="button"
        className="admin-panel__action-btn"
        disabled={!detail?.effective_setup}
        aria-expanded={showSetup}
        onClick={() => setShowSetup(!showSetup)}
      >
        Effective setup
      </button>
      <button type="button" className="admin-panel__action-btn" onClick={onClose}>Close</button>
    </>
  );

  return (
    <SettingsDrawer
      eyebrow={`Run · ${formatTime(row?.time ?? detail?.ended_at ?? null)} · ${row?.source ?? detail?.source ?? ""}`}
      title={row?.agent_label ?? detail?.agent_label ?? "Chat"}
      size="detail"
      onClose={onClose}
      footer={footer}
    >
      <RunFacts row={row} detail={detail} />
      {error ? <div className="ob-warn" role="alert">{error}</div> : null}
      {!detail && !error ? <span className="ob-muted">Loading the run…</span> : null}
      {detail ? (
        <>
          <RunSteps detail={detail} />
          <RunDecisionsAndCost detail={detail} />
          <RunSetupAndContent detail={detail} showSetup={showSetup} content={content} onShowContent={() => void showContent()} />
        </>
      ) : null}
    </SettingsDrawer>
  );
}
