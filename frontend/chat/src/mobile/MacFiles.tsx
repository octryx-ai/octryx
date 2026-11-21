// The files a chat's turns made on the Mac: listed by name; tapping one fetches it from the Mac
// through the platform and shows it here (pictures, text) or offers it as a download.

import { useEffect, useRef, useState } from "react";
import { macFileState, macFileUrl, requestMacFile } from "./mobileApi";
import { type MobileError } from "./mobileSession";
import { fileSize, macFileKind, type MacFile } from "./mobileFilesArtifacts";
import { SandboxedPage } from "./SandboxedPage";

const POLL_MS = 1500;
const MAX_POLLS = 100;
const MAX_TEXT = 200_000;
const MAX_PAGE = 2_000_000;

const REASONS: Record<string, string> = {
  device_paused: "Octryx is paused on your Mac.",
  device_runs_platform_disabled: "Runs on Macs are switched off right now.",
  too_many_open: "Wait for the files you already opened.",
  no_answer: "Your Mac did not answer. Is it online?",
  secret_file: "This looks like a secret; it stays on your Mac.",
  too_large: "Larger than 10 MB; open it on your Mac.",
  not_found: "The file is no longer on your Mac.",
  file_not_listed: "This file was not made in this chat.",
};

type Opened = {
  fileId: string;
  state: string;
  reason: string;
  text?: string;
};

function FileRow({ file }: { file: MacFile }) {
  const [opened, setOpened] = useState<Opened | null>(null);
  const alive = useRef(true);
  useEffect(
    () => () => {
      alive.current = false;
    },
    [],
  );
  const kind = macFileKind(file.name);

  const open = async () => {
    setOpened({ fileId: "", state: "pending", reason: "" });
    try {
      const { file: asked } = await requestMacFile(file.jobId, file.path);
      let current = asked;
      for (let poll = 0; poll < MAX_POLLS && alive.current; poll += 1) {
        if (current.state === "ready" || current.state === "failed") break;
        await new Promise((resolve) => window.setTimeout(resolve, POLL_MS));
        current = (await macFileState(file.jobId, asked.id)).file;
      }
      if (!alive.current) return;
      let text: string | undefined;
      if (current.state === "ready" && (kind === "text" || kind === "page")) {
        const response = await fetch(macFileUrl(file.jobId, asked.id), {
          credentials: "same-origin",
        });
        text = (await response.text()).slice(0, kind === "page" ? MAX_PAGE : MAX_TEXT);
      }
      setOpened({
        fileId: asked.id,
        state: current.state,
        reason: current.reason,
        text,
      });
    } catch (error) {
      setOpened({
        fileId: "",
        state: "failed",
        reason: (error as MobileError).code ?? "",
      });
    }
  };

  const ready = opened?.state === "ready" && opened.fileId;
  return (
    <details
      onToggle={(event) => {
        if ((event.target as HTMLDetailsElement).open && !opened) void open();
      }}
    >
      <summary>
        {file.path}
        <span className="m-muted"> · {fileSize(file.size)}</span>
      </summary>
      {opened && !ready && opened.state !== "failed" && (
        <p className="m-muted">Fetching from your Mac…</p>
      )}
      {opened?.state === "failed" && (
        <p className="m-error">
          {REASONS[opened.reason] ?? "The file could not be fetched."}{" "}
          <button type="button" className="m-copy" onClick={() => void open()}>
            Retry
          </button>
        </p>
      )}
      {ready && kind === "image" && (
        <img
          className="m-file-image"
          src={macFileUrl(file.jobId, opened.fileId)}
          alt={file.name}
        />
      )}
      {ready && kind === "text" && <pre>{opened.text}</pre>}
      {ready && kind === "page" && <SandboxedPage html={opened.text ?? ""} title={file.name} />}
      {ready && (
        <a
          className="m-copy"
          href={macFileUrl(file.jobId, opened.fileId, true)}
          download={file.name}
        >
          Download
        </a>
      )}
    </details>
  );
}

export function MacFiles({ files }: { files: MacFile[] }) {
  if (files.length === 0) return null;
  return (
    <section className="m-changes" aria-label="Files on your Mac">
      <span className="m-eyebrow">Files on your Mac · {files.length}</span>
      {files.map((file) => (
        <FileRow key={file.key} file={file} />
      ))}
    </section>
  );
}
