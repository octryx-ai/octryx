// Artifacts of a chat: the pages and designs its turns made, opened right in the app.
// - Claude Code artifacts from the Mac: published pages on claude.ai, opened there (your own claude.ai login).
// - Server chats: a page or an Office file as a sandboxed page, a diagram as a picture.
// Files a Mac turn wrote (HTML, SVG) are listed under "Files on your Mac" and open there the same way.

import { useState } from "react";
import { artifactImageUrl, loadArtifactPage } from "./mobileApi";
import { type MobileError } from "./mobileSession";
import type { ClaudeArtifact, ServerArtifact } from "./mobileFilesArtifacts";
import { SandboxedPage } from "./SandboxedPage";

const MAX_PAGE = 2_000_000;

function ServerRow({ item }: { item: ServerArtifact }) {
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState("");
  const open = async () => {
    if (item.kind !== "page" && item.kind !== "office") return;
    try {
      setHtml((await loadArtifactPage(item.path)).slice(0, MAX_PAGE));
    } catch (reason) {
      setError((reason as MobileError).status === 404 ? "The file is gone." : "The preview could not be loaded.");
    }
  };
  return (
    <details
      onToggle={(event) => {
        if ((event.target as HTMLDetailsElement).open && html === null && !error) void open();
      }}
    >
      <summary>{item.name}</summary>
      {item.kind === "diagram" && <img className="m-file-image" src={artifactImageUrl(item.path)} alt={item.name} />}
      {(item.kind === "page" || item.kind === "office") && html === null && !error && (
        <p className="m-muted">Loading…</p>
      )}
      {html !== null && <SandboxedPage html={html} title={item.name} />}
      {item.kind === "other" && <p className="m-muted">Open it in the web to see this file.</p>}
      {error && <p className="m-error">{error}</p>}
    </details>
  );
}

export function Artifacts({ claude, server }: { claude: ClaudeArtifact[]; server: ServerArtifact[] }) {
  if (claude.length + server.length === 0) return null;
  return (
    <section className="m-changes" aria-label="Artifacts">
      <span className="m-eyebrow">Artifacts · {claude.length + server.length}</span>
      {claude.map((item) => (
        <p key={item.key} className="m-artifact-link">
          <a href={item.url} target="_blank" rel="noopener noreferrer">
            Claude artifact · {item.url.split("/").pop()}
          </a>
        </p>
      ))}
      {server.map((item) => (
        <ServerRow key={item.key} item={item} />
      ))}
    </section>
  );
}
