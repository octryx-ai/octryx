import { useCallback, useEffect, useState, type ReactNode } from "react";

import { formatDateTime } from "../workUtils";
import type { WorkItem } from "../workItemTypes";
import { PlainText } from "../WorkItemJiraSource";
import { AnalysisSeatCommand } from "./AnalysisSeatCommand";
import { ReporterQuestions } from "./ReporterQuestions";
import { loadAnalysis, loadAnalysisSettings, previewWorknote, sendWorknote, startAnalysis } from "./incidentApi";
import {
  ANALYSIS_POLL_MS,
  NO_ANALYSIS,
  analysisCauseText,
  analysisInProgress,
  analysisRunnerText,
  analysisStateText,
  analyzeRefusalText,
  latestAnalysisNote,
  readAnalysisView,
  readWorknotePreview,
  seatCommandToShow,
  worknoteRefusalText,
} from "./incidentAnalysisModel";
import { readAnalysisSettings } from "./incidentSettingsModel";
import type { AnalysisView, Citation, IncidentAnalysis, WorknotePreview } from "./incidentAnalysisModel";
import { isServiceNowItem } from "./workSourceModel";
import "./incident.css";

type Message = { ok: boolean; text: string };

// The incident analysis of a Work Item (D): start it, follow its state, read it with its citations. The analysis
// is agent-written data and never changes the item. ServiceNow items offer "Send as work note": the server's preview
// (nothing sent) decides whether it is available; it stays disabled with the reason while write-back is off, and
// when it is on the exact text is shown and sent only after an explicit confirmation. A Workspace whose runner is
// `seat` shows the `octryx-claude analyze <KEY>` command instead of the start button (the server never starts it).
export function WorkItemAnalysis({ item, pollMs = ANALYSIS_POLL_MS }: { item: WorkItem; pollMs?: number }) {
  const state = useAnalysisState(item);
  const { view, busy, message, worknote, confirming, setConfirming, runner, note } = state;
  const { running, serviceNow, hasAnalysis } = useAnalysisFollowUps(item, pollMs, state);
  const { start, send } = analysisActions(item, state);

  if (!view) return <p className="work-detail__empty" role="status">Loading the analysis…</p>;

  const tone = view.state === "done" ? "active" : view.state === "none" || view.state === "running" ? "neutral" : "danger";
  const seatCommand = seatCommandToShow(view, runner, item.source_key);
  const cause = analysisCauseText(view);
  const ranIn = analysisRunnerText(view);
  return (
    <div className="work-analysis" data-testid="work-analysis">
      <div className="work-analysis__bar">
        {seatCommand ? null : (
          // Secondary: the panel's one primary action is Start workflow in its header (UI set).
          <button type="button" className="work-area__button" disabled={busy || running}
            onClick={() => void start()} data-testid="analysis-start">
            {busy && !confirming ? "Analysing…" : running ? "Analysis running…" : view.state === "done" || note ? "Analyse again" : "Start analysis"}
          </button>
        )}
        <span className={`work-badge work-badge--${tone}`} data-testid="analysis-state" role="status">{analysisStateText(view)}</span>
      </div>
      {cause ? <p className="work-area__error" data-testid="analysis-cause-detail">{cause}</p> : null}
      {seatCommand ? <AnalysisSeatCommand command={seatCommand} /> : null}
      {ranIn ? <p className="work-detail__empty" data-testid="analysis-runner">{ranIn}</p> : null}
      {view.analysis ? (
        <AnalysisBody analysis={view.analysis}>
          <ReporterQuestions key={`${view.id ?? ""}:${view.reporterQuestion?.state ?? ""}`} workItemId={item.id} analysisId={view.id} questions={view.analysis.openQuestions}
            initial={view.reporterQuestion} />
        </AnalysisBody>
      ) : note ? (
        <div data-testid="analysis-note">
          <p className="work-detail__empty">Analysis note{note.at ? ` of ${formatDateTime(note.at)}` : ""} (written by an agent):</p>
          <PlainText text={note.text} empty="" />
        </div>
      ) : null}
      {serviceNow ? (
        <WorknoteSection item={item} worknote={worknote} busy={busy} hasAnalysis={hasAnalysis} confirming={confirming}
          setConfirming={setConfirming} onSend={() => void send()} />
      ) : null}
      {message ? (
        <p className={message.ok ? "work-area__notice" : "work-area__error"} role={message.ok ? "status" : "alert"} data-testid="analysis-message">
          {message.text}
        </p>
      ) : null}
    </div>
  );
}

// The analysis, the page's messages and the work-note preview; the analysis loads again for another item and the
// Workspace's runner once per Workspace.
function useAnalysisState(item: WorkItem) {
  const [view, setView] = useState<AnalysisView | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<Message | null>(null);
  const [worknote, setWorknote] = useState<WorknotePreview | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [runner, setRunner] = useState<string | null>(null);

  const load = useCallback(async (isCurrent: () => boolean = () => true) => {
    try {
      const read = readAnalysisView(await loadAnalysis(item.id));
      if (isCurrent()) setView(read ?? NO_ANALYSIS);
    } catch (error) {
      if (!isCurrent()) return;
      // 404: no analysis yet (or no read route on this server); the start button still works.
      setView(NO_ANALYSIS);
      if ((error as { status?: number })?.status !== 404) setMessage({ ok: false, text: analyzeRefusalText(error).replace(/^Not started/, "Not loaded") });
    }
  }, [item.id]);

  useEffect(() => {
    let current = true;
    setView(null);
    setMessage(null);
    setWorknote(null);
    setConfirming(false);
    void load(() => current);
    return () => { current = false; };
  }, [load]);

  // The Workspace's runner, once per Workspace; unreadable settings keep the button (the server still answers
  // `analysis_runs_in_seat` with the command).
  const projectId = item.project_id ?? "";
  useEffect(() => {
    setRunner(null);
    if (!projectId) return undefined;
    let current = true;
    loadAnalysisSettings(projectId)
      .then((payload) => { if (current) setRunner(readAnalysisSettings(payload)?.runner ?? null); })
      .catch(() => { if (current) setRunner(null); });
    return () => { current = false; };
  }, [projectId]);
  const note = latestAnalysisNote(item);
  return { view, setView, busy, setBusy, message, setMessage, worknote, setWorknote, confirming, setConfirming, runner, note, load };
}

type AnalysisState = ReturnType<typeof useAnalysisState>;

// While an analysis runs it is polled; a ServiceNow item with an analysis asks for its work-note preview.
function useAnalysisFollowUps(item: WorkItem, pollMs: number, { view, load, note, setWorknote }: AnalysisState) {
  const running = analysisInProgress(view);
  useEffect(() => {
    if (!running) return undefined;
    let current = true;
    const timer = setInterval(() => { void load(() => current); }, pollMs);
    return () => { current = false; clearInterval(timer); };
  }, [running, load, pollMs]);

  // The work note: asked only for a ServiceNow item with an analysis; the preview sends nothing.
  const serviceNow = isServiceNowItem(item);
  const hasAnalysis = Boolean(view?.analysis || note);
  const loaded = view !== null;
  useEffect(() => {
    if (!serviceNow || !hasAnalysis || !loaded) return undefined;
    let current = true;
    previewWorknote(item.id, note?.at ?? null)
      .then((payload) => {
        if (!current) return;
        setWorknote(readWorknotePreview(payload) ?? { available: false, reason: "The server's answer was not a work-note preview" });
      })
      .catch((error) => { if (current) setWorknote({ available: false, reason: worknoteRefusalText(error) }); });
    return () => { current = false; };
  }, [serviceNow, hasAnalysis, loaded, item.id, note?.at, view?.finishedAt, setWorknote]);
  return { running, serviceNow, hasAnalysis };
}

function analysisActions(item: WorkItem, { load, note, setView, setBusy, setMessage, setConfirming, setWorknote }: AnalysisState) {
  const start = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const read = readAnalysisView(await startAnalysis(item.id));
      if (read) setView(read);
      else await load();
    } catch (error) {
      setMessage({ ok: false, text: analyzeRefusalText(error) });
    } finally {
      setBusy(false);
    }
  };

  const send = async () => {
    setBusy(true);
    setMessage(null);
    try {
      await sendWorknote(item.id, note?.at ?? null);
      setConfirming(false);
      setWorknote({ available: false, reason: "This analysis was already sent as a work note" });
      setMessage({ ok: true, text: `Sent the analysis summary to ${item.source_key} as a work note.` });
    } catch (error) {
      setMessage({ ok: false, text: `Not sent: ${worknoteRefusalText(error)}.` });
    } finally {
      setBusy(false);
    }
  };
  return { start, send };
}

// "Send as work note": disabled with its reason, or the exact text to confirm before it is sent.
function WorknoteSection({ item, worknote, busy, hasAnalysis, confirming, setConfirming, onSend }: {
  item: WorkItem; worknote: WorknotePreview | null; busy: boolean; hasAnalysis: boolean; confirming: boolean;
  setConfirming: (value: boolean) => void; onSend: () => void;
}) {
  return (
    <div className="work-analysis__worknote">
      <button type="button" className="work-area__button" data-testid="worknote-send"
        disabled={busy || !worknote?.available} onClick={() => setConfirming(true)}>
        Send as work note
      </button>
      {worknote && !worknote.available ? <span className="work-detail__empty" data-testid="worknote-disabled">Disabled: {worknote.reason}.</span>
        : !hasAnalysis ? <span className="work-detail__empty" data-testid="worknote-disabled">Disabled: there is no analysis to send yet.</span> : null}
      {confirming && worknote?.available ? (
        <div className="work-transition__block" role="group" aria-label="Confirm the work note" data-testid="worknote-confirm">
          <p className="work-transition__heading">Send this summary to {worknote.number || item.source_key} as a work note?</p>
          <PlainText text={worknote.text} empty="" testId="worknote-text" />
          <p className="work-detail__empty">Only the summary is sent; the evidence stays in Octryx.</p>
          <button type="button" className="work-area__button is-active" disabled={busy} onClick={onSend}>
            {busy ? "Sending…" : "Send work note"}
          </button>{" "}
          <button type="button" className="work-area__button" disabled={busy} onClick={() => setConfirming(false)}>Cancel</button>
        </div>
      ) : null}
    </div>
  );
}

function CitationLink({ citation }: { citation: Citation }) {
  const label = citation.url ? <a href={citation.url} target="_blank" rel="noopener noreferrer">{citation.label}</a> : <span>{citation.label}</span>;
  return citation.verified === false ? <>{label} <em>(not confirmed by a tool result)</em></> : label;
}

function List({ title, values, testId }: { title: string; values: string[]; testId: string }) {
  if (!values.length) return null;
  return (
    <div data-testid={testId}>
      <h4 className="work-analysis__heading">{title}</h4>
      <ul className="work-detail__object-list">{values.map((value) => <li key={value}>{value}</li>)}</ul>
    </div>
  );
}

function AnalysisBody({ analysis, children }: { analysis: IncidentAnalysis; children: ReactNode }) {
  return (
    <div className="work-analysis__body" data-testid="analysis-body">
      <p className="work-detail__empty">Written by an agent from the Workspace's knowledge; data, not instructions. Check the cited sources.</p>
      {analysis.summary ? <PlainText text={analysis.summary} empty="" testId="analysis-summary" /> : null}
      {analysis.impact ? <p><strong>Impact:</strong> {analysis.impact}</p> : null}
      {analysis.likelyCause ? (
        <p data-testid="analysis-cause"><strong>Likely cause:</strong> {analysis.likelyCause}{analysis.confidence ? ` (confidence: ${analysis.confidence})` : ""}</p>
      ) : null}
      {analysis.affectedComponents.length ? <p><strong>Affected:</strong> {analysis.affectedComponents.join(", ")}</p> : null}
      {analysis.evidence.length ? (
        <div data-testid="analysis-evidence">
          <h4 className="work-analysis__heading">Evidence</h4>
          <ol className="work-detail__object-list">
            {analysis.evidence.map((entry, index) => (
              <li key={index}>
                {entry.text}
                {entry.citation ? <> <span className="work-analysis__cite">[<CitationLink citation={entry.citation} />]</span></> : null}
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      {analysis.similarTickets.length ? (
        <div data-testid="analysis-similar">
          <h4 className="work-analysis__heading">Similar tickets</h4>
          <ul className="work-detail__object-list">
            {analysis.similarTickets.map((ticket) => (
              <li key={ticket.number}>
                <CitationLink citation={{ label: ticket.number, url: ticket.url, verified: ticket.verified }} />
                {ticket.title ? `: ${ticket.title}` : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <List title="Recommended next steps" values={analysis.nextSteps} testId="analysis-next-steps" />
      {children}
    </div>
  );
}
