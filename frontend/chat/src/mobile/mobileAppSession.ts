// The phone app's sign-in and session renewal, data loading and polling, and opening a notified item.
import { useCallback, useEffect } from "react";
import { claimPhone, onSignedOut, startSession } from "./mobileSession";
import { parseHash } from "./mobileDeviceChats";
import { storeWorkspaceChoice } from "./mobileWorkspace";
import { loadMobileAppData } from "./mobileAppLoad";
import { approvalOfItem } from "./phoneApprovals";
import { useRefreshEvent } from "./pullToRefresh";
import { useMobileOpeners } from "./useMobileOpeners";
import { browserStore, type MobileAppState } from "./mobileAppState";

const REFRESH_MS = 4 * 60 * 1000;
const POLL_MS = 30000;

export function useMobileSignIn(
  { setChoice, setSession, setPhase, phase }: MobileAppState,
  pairing: boolean,
  confirming: boolean,
) {
  const chooseWorkspace = useCallback((id: string) => {
    storeWorkspaceChoice(browserStore(), id);
    setChoice(id);
  }, [setChoice]);

  const signIn = useCallback(async (claim?: string) => {
    if (claim) await claimPhone(claim);
    const started = await startSession();
    window.history.replaceState(null, "", "/m/");
    setSession(started);
    setPhase("ready");
  }, [setSession, setPhase]);

  useEffect(() => {
    if (pairing || confirming) return;
    const claim = parseHash(window.location.hash).claim;
    signIn(claim).catch(() => {
      // A stale claim from the Home Screen address: the phone may still hold a valid credential.
      (claim ? signIn() : Promise.reject(new Error("signed out"))).catch(() => setPhase("signedOut"));
    });
    return onSignedOut(() => setPhase("signedOut"));
  }, [pairing, confirming, signIn, setPhase]);

  useEffect(() => {
    if (phase !== "ready") return;
    const renew = () => startSession().then(setSession, () => setPhase("signedOut"));
    const timer = window.setInterval(renew, REFRESH_MS);
    const visible = () => document.visibilityState === "visible" && renew();
    document.addEventListener("visibilitychange", visible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [phase, setSession, setPhase]);
  return { chooseWorkspace, signIn };
}

export function useMobileLoad(state: MobileAppState) {
  const {
    choice, setLoading, setThreads, setProjects, setSessions, setLocalSessions, setLiveSessions, setCases, setRunRows,
    setOpenTasks, setMyTasks, setDevices, setItems, setApprovals, setUsage, setError, phase, detail, tab,
  } = state;
  const load = useCallback(
    () =>
      loadMobileAppData(choice, {
        setLoading, setThreads, setProjects, setSessions, setLocalSessions, setLiveSessions, setCases, setRunRows,
        setOpenTasks, setMyTasks, setDevices, setItems, setApprovals, setUsage, setError,
      }),
    [choice, setLoading, setThreads, setProjects, setSessions, setLocalSessions, setLiveSessions, setCases, setRunRows,
      setOpenTasks, setMyTasks, setDevices, setItems, setApprovals, setUsage, setError],
  );

  const onTabPage = phase === "ready" && detail === null;
  useRefreshEvent(() => onTabPage && tab !== "work" && load());

  useEffect(() => {
    if (!onTabPage) return;
    void load();
    const timer = window.setInterval(() => !document.hidden && void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [onTabPage, load]);
  return load;
}

export function useMobileItemLinks(state: MobileAppState, load: () => Promise<void>) {
  const { threads, liveSessions, localSessions, openPage, resetPages, setTab, setPendingItem } = state;
  const { pendingItem, items, approvals, loading } = state;
  const openers = useMobileOpeners({ threads, liveSessions, localSessions, openPage });
  const { openItem } = openers;

  useEffect(() => {
    const opened = () => {
      const item = parseHash(window.location.hash).item;
      if (!item) return;
      window.history.replaceState(null, "", "/m/");
      resetPages();
      setTab("home");
      setPendingItem(item);
      void load();
    };
    window.addEventListener("hashchange", opened);
    return () => window.removeEventListener("hashchange", opened);
  }, [load, resetPages, setTab, setPendingItem]);

  useEffect(() => {
    if (!pendingItem || items === null || loading) return;
    setPendingItem("");
    const approval = approvalOfItem(pendingItem, approvals);
    const item = items.find((candidate) => candidate.key === pendingItem);
    if (approval) openPage({ kind: "approval", approval });
    else if (item) openItem(item);
  }, [pendingItem, items, approvals, loading, openItem, openPage, setPendingItem]);
  return openers;
}
