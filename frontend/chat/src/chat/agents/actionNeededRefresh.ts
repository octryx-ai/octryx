// Lets the bell reload at once instead of waiting for its 30 s poll.

export const ACTION_NEEDED_REFRESH_EVENT = "octryx-action-needed-refresh";

export function requestActionNeededRefresh() {
  window.dispatchEvent(new CustomEvent(ACTION_NEEDED_REFRESH_EVENT));
}
