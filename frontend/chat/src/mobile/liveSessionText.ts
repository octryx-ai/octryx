// Refusal texts and the fork bar rules of a live session page.

export const REFUSALS: Record<string, string> = {
  live_unavailable: "Your Mac does not report its sessions right now.",
  session_not_running: "This session is no longer running.",
  rate_limited: "Too many messages in a minute. Wait a moment.",
  too_many_open: "Your Mac has not confirmed the last messages yet.",
  text_invalid: "The message is empty or too long.",
  image_too_large: "A picture is too large.",
  image_type_refused: "Only pictures (PNG, JPEG, WebP) can be attached.",
  images_invalid: "At most 3 pictures per message.",
  picture_unreadable: "This picture could not be read.",
  picture_too_large: "This picture is too large, even made smaller.",
};

export type Picture = { key: string; preview: string; data: string };

// The fork bar always says why its button is greyed out (it must never look usable while
// the session works).
export const forkBlocked = (running: boolean, status: string, draft: string, forking: boolean) =>
  !running || status === "Working…" || !draft.trim() || forking;
export const forkReason = (running: boolean, status: string, draft: string, forking: boolean) =>
  forking
    ? "Starting the copy…"
    : !running
      ? "The session is not reporting right now; a copy can start once it does."
      : status === "Working…"
        ? "Greyed out while the session works: a copy can start once it is idle."
        : !draft.trim()
          ? "Write the copy's first message below, then fork. The terminal session stays untouched."
          : "Continue a copy here as a Mac chat: the terminal session stays untouched, every write step asks you first.";

export const FORK_REFUSALS: Record<string, string> = {
  session_busy: "The session is working. Fork it once it is idle.",
  takeover_not_allowed_on_device:
    "This profile does not allow remote runs. On the Mac: octryx-claude profiles connect … --allow-takeover.",
  device_offline: "Your Mac is offline.",
  device_paused: "Octryx is paused on your Mac.",
  session_not_running: "This session is no longer running.",
};
