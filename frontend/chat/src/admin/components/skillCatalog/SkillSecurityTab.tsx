import { useState } from "react";

import { CheckRow } from "./SkillBadges";
import { saveDraft } from "./skillCatalogApi";
import { refusalText } from "./skillCatalogModel";
import type { Finding, SkillDetail, SkillVersion } from "./skillCatalogTypes";
import {
  SEVERITY_LABELS, SEVERITY_MARK, findingPlace, findingsBySeverity, sameIds, scriptFiles, toggleId,
} from "./skillDetailModel";

// Detail → Security (mock `securityHtml`, `helmSecurityHtml`, `mcpSecurityHtml`): the automated review of the working
// version grouped by severity, what is new against the published version, the spec checks, and — on an open draft
// only — acknowledging findings and allowing scripts (with a required reason). Finding texts are shown as given; the
// API never returns secret values.
export function SkillSecurityTab({ detail, version, onChanged }: {
  detail: SkillDetail;
  version: SkillVersion;
  onChanged: (message: string) => Promise<void>;
}) {
  const draft = detail.open?.state === "draft" && detail.open.version === version.version ? detail.open : null;
  const [acked, setAcked] = useState<string[]>(version.acknowledged_findings ?? []);
  const [scriptsOn, setScriptsOn] = useState(version.scripts_allowed);
  const [reason, setReason] = useState(version.scripts_reason ?? "");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const scripts = scriptFiles(version.files);
  const ackChanged = !sameIds(acked, version.acknowledged_findings ?? []);
  const scriptsChanged = scriptsOn !== version.scripts_allowed || (scriptsOn && reason !== (version.scripts_reason ?? ""));

  const save = async (body: Record<string, unknown>, done: string) => {
    if (!draft) return;
    setBusy(true);
    setProblem(null);
    try {
      await saveDraft(detail.id, draft.version, body, draft.digest);
      await onChanged(done);
    } catch (error) {
      setProblem(refusalText(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div data-testid="skill-security">
      {detail.open && detail.published ? (detail.new_findings.length ? (
        <div className="policies__warn" data-testid="skill-new-findings">
          <b>{detail.new_findings.length} new finding{detail.new_findings.length === 1 ? "" : "s"}</b> against the published
          v{detail.published.version}: {detail.new_findings.map((item) => `${item.rule}${item.file ? ` (${item.file})` : ""}`).join(", ")}.
        </div>
      ) : <div className="policies__note" data-testid="skill-new-findings">No new findings against the published v{detail.published.version}.</div>) : null}

      <ReviewCard version={version} draft={Boolean(draft)} acked={acked} busy={busy} ackChanged={ackChanged}
        onAck={(id, on) => setAcked((ids) => toggleId(ids, id, on))}
        onSave={() => void save({ acknowledged_findings: acked }, "Acknowledgements saved to the draft.")} />

      <ScriptsCard version={version} draft={Boolean(draft)} scripts={scripts} scriptsOn={scriptsOn} reason={reason} busy={busy}
        changed={scriptsChanged} onScriptsOn={setScriptsOn} onReason={setReason}
        onSave={() => void save(scriptsOn ? { scripts_allowed: true, scripts_reason: reason.trim() } : { scripts_allowed: false },
          scriptsOn ? "Scripts allowed in the draft." : "Scripts withheld in the draft.")} />
      {problem ? <p className="policies__warn skill-detail__gap" role="alert">{problem}</p> : null}
    </div>
  );
}

function FindingRow({ finding, draft, done, busy, onAck }: { finding: Finding; draft: boolean; done: boolean; busy: boolean; onAck: (on: boolean) => void }) {
  const mark = SEVERITY_MARK[finding.severity];
  const hint = [findingPlace(finding), `on delivery: ${finding.effect}`, finding.blocks ? "blocks publishing" : ""].filter(Boolean).join(" · ");
  return (
    <div className="skills__check" data-testid={`skill-finding-${finding.id}`}>
      <span className={`skills__check-i ${mark.tone}`}>{mark.icon}</span>
      <span>
        <b>{finding.rule}</b> — {finding.message}
        <div className="skills__hint">{hint}</div>
        {finding.acknowledge ? (draft ? (
          <label className="skills__cbx">
            <input type="checkbox" checked={done} disabled={busy} data-testid={`skill-finding-ack-${finding.id}`}
              onChange={(event) => onAck(event.target.checked)} />
            Acknowledged for this version
          </label>
        ) : <div className="skills__hint">{done ? "Acknowledged" : "Not acknowledged"}</div>) : null}
      </span>
    </div>
  );
}

function ReviewCard({ version, draft, acked, busy, ackChanged, onAck, onSave }: {
  version: SkillVersion; draft: boolean; acked: string[]; busy: boolean; ackChanged: boolean;
  onAck: (id: string, on: boolean) => void; onSave: () => void;
}) {
  const report = version.security_report;
  return (
    <div className="admin-panel__card skill-detail__gap">
      <div className="admin-panel__section-header">Automated review of v{version.version}{" "}
        <span className="skills__hint" style={{ textTransform: "none", letterSpacing: 0 }}>runs on every draft save</span></div>
      {report.spec.map((issue, index) => (
        <CheckRow key={`${issue.code}-${index}`} tone={issue.severity === "error" ? "er" : "wa"} title={`Spec${issue.field ? ` · ${issue.field}` : ""}`}>{issue.message}</CheckRow>
      ))}
      {findingsBySeverity(report.findings).map((group) => (
        <div key={group.severity}>
          <div className="skills__tree-label">{SEVERITY_LABELS[group.severity]} · {group.findings.length}</div>
          {group.findings.map((finding) => (
            <FindingRow key={finding.id} finding={finding} draft={draft} done={acked.includes(finding.id)} busy={busy}
              onAck={(on) => onAck(finding.id, on)} />
          ))}
        </div>
      ))}
      {report.spec.length || report.findings.length ? null : <CheckRow tone="ok">No findings and no spec issues.</CheckRow>}
      {draft && report.findings.some((item) => item.acknowledge) ? (
        <div className="policies__row skill-detail__gap">
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy || !ackChanged}
            data-testid="skill-findings-save" onClick={onSave}>Save acknowledgements</button>
        </div>
      ) : null}
    </div>
  );
}

function ScriptsCard({ version, draft, scripts, scriptsOn, reason, busy, changed, onScriptsOn, onReason, onSave }: {
  version: SkillVersion; draft: boolean; scripts: ReturnType<typeof scriptFiles>; scriptsOn: boolean; reason: string; busy: boolean;
  changed: boolean; onScriptsOn: (on: boolean) => void; onReason: (reason: string) => void; onSave: () => void;
}) {
  return (
    <div className="admin-panel__card skill-detail__gap" data-testid="skill-scripts">
      <div className="admin-panel__section-header">Scripts for this version</div>
      {!scripts.length ? <p className="skills__hint">This version has no scripts, so there is nothing to allow.</p> : draft ? (
        <>
          <div className="skills__toggle">
            <span>Allow scripts for this version
              <small>Off: {scripts.map((file) => file.path).join(", ")} {scripts.length === 1 ? "is" : "are"} not delivered. On: delivered
                read-only to octryx-claude; running one is still a Bash tool call checked by the Workspace tool policy and the platform policies.</small></span>
            <button type="button" role="switch" aria-checked={scriptsOn} aria-label="Allow scripts for this version" disabled={busy}
              className={`skills__switch${scriptsOn ? " is-on" : ""}`} data-testid="skill-scripts-switch" onClick={() => onScriptsOn(!scriptsOn)} />
          </div>
          {scriptsOn ? (
            <label className="admin-panel__field skill-detail__gap"><span>Reason (required)</span>
              <textarea className="skill-detail__reason" value={reason} maxLength={500} placeholder="Why this version may deliver its scripts"
                data-testid="skill-scripts-reason" onChange={(event) => onReason(event.target.value)} /></label>
          ) : null}
          <div className="policies__row skill-detail__gap">
            <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="skill-scripts-save"
              disabled={busy || !changed || (scriptsOn && !reason.trim())}
              onClick={onSave}>Save to draft</button>
          </div>
        </>
      ) : (
        <p className="skills__hint">
          {version.scripts_allowed ? <>Allowed for this version{version.scripts_reason ? `: ${version.scripts_reason}` : ""}.</>
            : <>Withheld: {scripts.map((file) => file.path).join(", ")}. Allowing scripts is a draft change.</>}
        </p>
      )}
    </div>
  );
}
