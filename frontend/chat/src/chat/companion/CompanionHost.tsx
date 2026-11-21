import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { browserNotificationApi, type NotificationApi } from "../agents/browserNotifications";
import { CompanionPanel } from "./CompanionPanel";
import { badgeCount } from "./companionGroups";
import { companionLabel, faceState } from "./companionModel";
import { OctryxLogo } from "./OctryxLogo";
import { usePrefersReducedMotion } from "./usePrefersReducedMotion";
import { useCompanion } from "./useCompanion";
import "./companion.css";

// Octryx lives in the logo at the top left (product inventory, step 1): one host owns the attention state, the live
// socket and the side panel; the logo in the rail (and in the compact menu on narrow screens) is its trigger, with
// the count of what needs the person plus problems as a dot. No floating button.

type CompanionControl = {
  open: boolean;
  toggle: () => void;
  label: string;
  count: number;
  state: "worry" | "open" | "calm" | "sleep";
  working: boolean;
  reducedMotion: boolean;
};

const CompanionContext = createContext<CompanionControl | null>(null);

export function CompanionHost({ children, userId, onOpenAgents, onOpenSession, isAdmin = false, notificationApi, pollMs, socket = true, answeredMs }: {
  children?: ReactNode;
  userId?: string | null;
  onOpenAgents: () => void;
  onOpenSession?: (sessionId: string) => void;
  isAdmin?: boolean;
  notificationApi?: NotificationApi | null;
  pollMs?: number;
  socket?: boolean;
  answeredMs?: number;
}) {
  const api = notificationApi === undefined ? browserNotificationApi() : notificationApi;
  const [open, setOpen] = useState(false);
  const reducedMotion = usePrefersReducedMotion();
  const openItem = useCallback(() => setOpen(true), []);
  const { attention, problem, reload, remove, watchJob } = useCompanion({ userId: userId ?? "", notificationApi: api, onOpenItem: openItem, pollMs, socket });
  const label = companionLabel(attention);
  const count = badgeCount(attention?.items ?? []);
  const state = faceState(attention);
  const working = (attention?.running ?? []).some((run) => run.state === "working");
  const toggle = useCallback(() => setOpen((value) => !value), []);
  const control = useMemo(
    () => ({ open, toggle, label, count, state, working, reducedMotion }),
    [open, toggle, label, count, state, working, reducedMotion],
  );

  return (
    <CompanionContext.Provider value={control}>
      {children}
      {open ? (
        <CompanionPanel attention={attention} problem={problem} onClose={() => setOpen(false)}
          onDone={(key) => { remove(key); reload(); }}
          onOpenAgents={() => { setOpen(false); onOpenAgents(); }}
          footer={{ userId: userId ?? "", notificationApi: api }} watchJob={watchJob}
          onOpenSession={onOpenSession} isAdmin={isAdmin} answeredMs={answeredMs} />
      ) : null}
    </CompanionContext.Provider>
  );
}

/**
 * The logo as the companion's trigger. Outside a host (tests, isolated renders) it is the plain logo linking to chat,
 * like a plain rail logo. `glyph` replaces the Octryx AI logo for a custom tenant brand.
 */
export function CompanionLogoTrigger({ className = "", glyph, testId = "octryx-button" }: {
  className?: string;
  glyph?: ReactNode;
  testId?: string;
}) {
  const control = useContext(CompanionContext);
  const mark = glyph ?? <OctryxLogo />;
  if (!control) {
    return <a className={`octryx-trigger ${className}`.trim()} href="/chat" aria-label="Open chat">{mark}</a>;
  }
  const { open, toggle, label, count, state, working, reducedMotion } = control;
  return (
    <button type="button" className={`octryx-trigger ${className}`.trim()} aria-label={label} title={label}
      aria-expanded={open} data-state={state} data-working={working ? "true" : undefined}
      data-motion={reducedMotion ? "reduced" : "full"}
      onClick={toggle} data-testid={testId}>
      {mark}
      {count ? <span className="octryx-trigger__count" data-testid="octryx-count">{count > 99 ? "99+" : count}</span> : null}
    </button>
  );
}
