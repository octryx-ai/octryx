import { useCallback, useEffect, useState } from "react";

import { resolveHelpDoc } from "../../help/helpDocs";
import { HELP_DOCS } from "../../help/helpLibrary";
import { LoadingState } from "../../layout/LoadingState";
import { PageHeader } from "../../layout/PageHeader";
import type { ProjectOption } from "../../chatOptionTypes";
import { useActiveWorkspace } from "../useActiveWorkspace";
import { loadSetupStatus } from "./setupGuideApi";
import {
  applySkips,
  readSkips,
  setupSummary,
  stepHref,
  unknownSteps,
  writeSkips,
  type SetupStatus,
  type SetupStep,
} from "./setupGuideModel";
import "./setup-guide.css";

const MARK: Record<SetupStep["status"], { mark: string; words: string }> = {
  done: { mark: "✓", words: "Done" },
  open: { mark: "○", words: "Open" },
  attention: { mark: "!", words: "Needs attention" },
  skipped: { mark: "–", words: "Skipped" },
  unknown: { mark: "○", words: "" },
};

function browserStore(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** Title, benefit sentence and the button of a step, from help/setup/<step>.md. */
function stepText(key: string) {
  const doc = resolveHelpDoc(HELP_DOCS, "setup", key);
  const body = doc?.page === key ? doc.body : "";
  const benefit = body.split("\n").find((line) => line.trim() && !line.startsWith("#")) ?? "";
  const link = /\[([^\]]+)\]\((\/chat\?[^)]+)\)/.exec(body);
  return { title: doc?.page === key ? doc.title : key, benefit, linkLabel: link?.[1] ?? "Open", link: link?.[2] ?? "/chat" };
}

// A step's level in words. A Workspace step decided by a platform fact (a shared connection) says so.
function scopeLabel(step: { key: string; scope: string }, workspaceName: string): string {
  if (step.scope === "platform") return PLATFORM_STEP_KEYS.has(step.key) ? "Platform" : "Platform · shared";
  return workspaceName ? `Workspace ${workspaceName}` : "Workspace";
}

const PLATFORM_STEP_KEYS = new Set(["workspace", "models", "sso"]);

// The button names the page it opens when the server points a step elsewhere (Models → Default & fallback).
const TARGET_LABEL: Record<string, string> = { modelOrder: "Open Default & fallback", providers: "Open Providers" };

// The Setup guide: the platform steps and the steps of the Workspace chosen in the global switch, each
// with one sentence of benefit and one button into the page where it is done. Members see the steps without status.
export function SetupGuidePage({ projects, fallbackWorkspaceId, userId, isAdmin }: {
  projects: ProjectOption[];
  fallbackWorkspaceId?: string | null;
  userId?: string | null;
  isAdmin: boolean;
}) {
  const [workspaceId] = useActiveWorkspace(projects, fallbackWorkspaceId);
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [loading, setLoading] = useState(isAdmin);
  const [problem, setProblem] = useState<string | null>(null);
  const [skipped, setSkipped] = useState(() => readSkips(browserStore(), userId));

  const load = useCallback(() => {
    if (!isAdmin) return;
    setLoading(true);
    setProblem(null);
    loadSetupStatus(workspaceId || null)
      .then(setStatus)
      .catch(() => setProblem("The setup status could not be loaded."))
      .finally(() => setLoading(false));
  }, [isAdmin, workspaceId]);
  useEffect(load, [load]);

  const steps = applySkips(status?.steps ?? unknownSteps(), skipped);
  const summary = setupSummary(steps);
  // One bright button: the next step to do (one primary action per page).
  const nextKey = steps.find((step) => step.status === "open" || step.status === "attention")?.key ?? null;
  const workspaceName = status?.workspace?.name ?? projects.find((project) => project.id === workspaceId)?.name ?? "";
  const toggleSkip = (key: string) => {
    const next = new Set(skipped);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setSkipped(next);
    writeSkips(browserStore(), userId, next);
  };

  return (
    <main className="setup-guide" data-testid="setup-guide">
      <PageHeader eyebrow="Help" title="Setup guide"
        purpose={workspaceName ? `Set up the platform, and the Workspace ${workspaceName}, step by step.` : "Set up the platform step by step."}
        secondary={isAdmin && status ? <span className="setup-guide__count">{summary.done} of {summary.total} done</span> : null} />
      <div className="setup-guide__body">
        {loading && !status ? <LoadingState label="the setup status" rows={7} onRetry={load} /> : null}
        {problem ? <p className="admin-panel__error" role="alert">{problem}</p> : null}
        {!isAdmin ? <p className="admin-panel__hint">An administrator sees which steps are done.</p> : null}
        {!loading || status ? (
          <ol className="setup-guide__steps">
            {steps.map((step, index) => {
              const content = stepText(step.key);
              return (
                <li key={step.key} className={`setup-guide__step setup-guide__step--${step.status}`} data-step={step.key} data-status={step.status}>
                  <span className="setup-guide__mark" aria-hidden="true">{step.status === "unknown" ? index + 1 : MARK[step.status].mark}</span>
                  <div className="setup-guide__copy">
                    <div className="setup-guide__title">
                      <strong>{content.title}</strong>
                      {step.recommended ? <span className="work-badge work-badge--neutral">Recommended</span> : null}
                      {MARK[step.status].words ? <span className="setup-guide__state">{MARK[step.status].words}</span> : null}
                      <span className="setup-guide__scope">{scopeLabel(step, workspaceName)}</span>
                    </div>
                    <p>{content.benefit}</p>
                    {step.status === "attention" && step.reason ? <p className="setup-guide__reason" role="note">{step.reason}</p> : null}
                    {step.status === "done" && step.reason ? <p className="setup-guide__note">{step.reason}</p> : null}
                    {step.key === "agents" ? (
                      <a className="setup-guide__follow-up" href={stepHref("/chat?area=workflows&tab=agents", step, workspaceId || null)}>
                        Optional: create your own agent
                      </a>
                    ) : null}
                  </div>
                  <div className="setup-guide__actions">
                    <a className={`admin-panel__action-btn${step.key === nextKey ? " admin-panel__action-btn--primary" : ""}`}
                      href={stepHref(content.link, step, workspaceId || null)}>
                      {step.target ? TARGET_LABEL[step.target] ?? content.linkLabel : content.linkLabel}
                    </a>
                    {step.recommended && step.status !== "done" && isAdmin ? (
                      <button type="button" className="admin-panel__action-btn" onClick={() => toggleSkip(step.key)}>
                        {step.status === "skipped" ? "Resume" : "Skip for now"}
                      </button>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ol>
        ) : null}
      </div>
    </main>
  );
}
