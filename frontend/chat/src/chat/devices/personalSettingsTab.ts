// The page My settings shows (`?area=personal&tab=<page>`): the account menu opens Profile or Devices, a run card
// links to Profile (link your account). A tiny store, so an open My settings follows the menu.
export type PersonalTab = "profile" | "devices" | "notifications";

// Pages with their own `tab` in the URL; Devices is the default without one.
const URL_TABS: PersonalTab[] = ["profile", "notifications"];

const EVENT = "octryx:personal-tab";

export function readPersonalTab(search: string): PersonalTab {
  try {
    const params = new URLSearchParams(search);
    const tab = params.get("tab") as PersonalTab | null;
    return params.get("area") === "personal" && tab && URL_TABS.includes(tab) ? tab : "devices";
  } catch {
    return "devices";
  }
}

let pendingTab: PersonalTab | null = null;

/** Show `tab` in My settings: an open one switches at once, one about to mount starts on it. */
export function openPersonalTab(tab: PersonalTab) {
  if (typeof window === "undefined") return;
  pendingTab = tab;
  window.dispatchEvent(new CustomEvent<PersonalTab>(EVENT, { detail: tab }));
}

/** The tab the menu asked for before My settings mounted (read once). */
export function takePendingPersonalTab(): PersonalTab | null {
  const tab = pendingTab;
  pendingTab = null;
  return tab;
}

export function onPersonalTab(listener: (tab: PersonalTab) => void): () => void {
  const handler = (event: Event) => {
    pendingTab = null;
    listener((event as CustomEvent<PersonalTab>).detail);
  };
  window.addEventListener(EVENT, handler);
  return () => window.removeEventListener(EVENT, handler);
}
