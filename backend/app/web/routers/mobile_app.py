"""Octryx Mobile, the Home Screen web app: its page, manifest and service worker under ``/m``.

- ``GET /m``, ``/m/``, ``/m/pair``, ``/m/confirm`` (the Mac's browser confirms a phone): the app's one HTML page
  (``static/chat/m/index.html``, built by Vite). It needs no login to load: the app signs itself in with its own
  phone credential (``/api/v1/mobile/session``) or shows how to connect. ``no-store``, like the chat page.
- ``GET /m/manifest.webmanifest``: name, icons, ``start_url``/``scope`` ``/m/``, standalone.
- ``GET /m/sw.js``: a minimal service worker (scope ``/m/``): it caches nothing and answers a failed page load
  with a short offline notice (the platform is only reachable over the VPN). It also shows the platform's
  notifications (Web Push), sets the app icon's badge and opens the entry a notification is about.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from .._helpers.api_guards import _chat_app_dir

router = APIRouter()

NO_STORE = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache", "Expires": "0"}
ICON_BASE = "/admin/static/chat/m"
BACKGROUND = "#0e100f"

MANIFEST = {
    "name": "Octryx",
    "short_name": "Octryx",
    "description": "Your Octryx sessions on your phone",
    "start_url": "/m/",
    "scope": "/m/",
    "display": "standalone",
    "background_color": BACKGROUND,
    "theme_color": BACKGROUND,
    "icons": [
        {"src": f"{ICON_BASE}/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": f"{ICON_BASE}/icon-512.png", "sizes": "512x512", "type": "image/png"},
    ],
}

SERVICE_WORKER = """// Octryx Mobile service worker (scope /m/): no caching; a failed page load gets an offline notice.
const OFFLINE = `<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Octryx</title>
<body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#0e100f;
color:#efece4;font:16px -apple-system,system-ui,sans-serif;text-align:center;padding:24px">
<div><p style="font-size:20px;font-weight:600">Octryx can't reach the platform</p>
<p style="color:#898f86">Check that the VPN is on, then open Octryx again.</p></div>`;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(fetch(event.request).catch(() =>
    new Response(OFFLINE, { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } })));
});

// Phase 3: a notification from the platform (encrypted Web Push); the badge counts what needs the person.
self.addEventListener("push", (event) => {
  let message = {};
  try { message = event.data ? event.data.json() : {}; } catch (_) { message = {}; }
  const url = typeof message.url === "string" && message.url.startsWith("/m/") ? message.url : "/m/";
  const badge = Number.isInteger(message.badge) && message.badge >= 0 ? message.badge : null;
  const shown = self.registration.showNotification(String(message.title || "Octryx"), {
    body: String(message.body || ""), tag: String(message.tag || "octryx"), data: { url },
    icon: "/admin/static/chat/m/icon-192.png", badge: "/admin/static/chat/m/icon-192.png",
  });
  const badged = badge === null || !self.navigator.setAppBadge ? Promise.resolve()
    : (badge ? self.navigator.setAppBadge(badge) : self.navigator.clearAppBadge()).catch(() => undefined);
  event.waitUntil(Promise.all([shown, badged]));
});
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/m/";
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((open) => {
    const app = open.find((client) => {
      const path = new URL(client.url).pathname;
      return path === "/m" || path.startsWith("/m/");
    });
    if (app) return app.focus().then((client) => client.navigate(url)).catch(() => self.clients.openWindow(url));
    return self.clients.openWindow(url);
  }));
});
"""


def _index_path():
    return _chat_app_dir() / "m" / "index.html"


@router.api_route("/m", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
@router.api_route("/m/", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
@router.api_route("/m/pair", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
@router.api_route("/m/confirm", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
async def mobile_page():
    index = _index_path()
    if not index.exists():
        return HTMLResponse("Octryx Mobile is not built on this platform.", status_code=503, headers=NO_STORE)
    return FileResponse(index, headers=NO_STORE)


@router.get("/m/manifest.webmanifest", include_in_schema=False)
async def mobile_manifest():
    return JSONResponse(MANIFEST, media_type="application/manifest+json", headers={"Cache-Control": "no-cache"})


@router.get("/m/sw.js", include_in_schema=False)
async def mobile_service_worker():
    return Response(SERVICE_WORKER, media_type="text/javascript",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/m/"})


__all__ = ["router"]
