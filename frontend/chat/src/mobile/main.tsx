// Octryx Mobile's entry (served by the backend at /m). The pairing page gets no manifest, so "Add to Home Screen"
// keeps the address it hands over (/m/#claim=…), nor does the Mac's confirmation page; the app page links the
// manifest and registers the service worker.
import { createRoot } from "react-dom/client";
import { MobileApp } from "./MobileApp";
import { RefreshShell } from "./RefreshShell";
import { installStaleBuildReload } from "../staleBuild";
// The design system's tokens and blocks (StatusLabel), then the phone's own styles, which define the base tokens.
import "../styles/chat/ds-tokens.css";
import "../styles/chat/design-system.css";
import "./mobile.css";
import "../styles/chat/ui-set.css";

const appPage = !["/m/pair", "/m/confirm"].includes(
  window.location.pathname.replace(/\/+$/, ""),
);
if (appPage) {
  const link = document.createElement("link");
  link.rel = "manifest";
  link.href = "/m/manifest.webmanifest";
  document.head.appendChild(link);
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker
      .register("/m/sw.js", { scope: "/m/" })
      .catch(() => undefined);
  }
}

installStaleBuildReload();

const root = document.getElementById("root");
if (root)
  createRoot(root).render(
    <RefreshShell>
      <MobileApp />
    </RefreshShell>,
  );
