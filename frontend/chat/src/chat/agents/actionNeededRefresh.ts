// LA-1 (live acceptance): after the user decides, releases or redacts, the bell reloads its action-needed count
// at once instead of waiting for its 30 s poll. The action announces itself; the app-wide bell listens.

export const ACTION_NEEDED_REFRESH_EVENT = "octryx-action-needed-refresh";

export function requestActionNeededRefresh() {
  window.dispatchEvent(new CustomEvent(ACTION_NEEDED_REFRESH_EVENT));
}
