import { useEffect, useState } from "react";

import { loadOctryxInstall } from "./octryxInstallApi";
import { installErrorText, macosCommand, readOctryxInstall, windowsCommand } from "./octryxInstallModel";
import type { OctryxInstall } from "./octryxInstallModel";

// "Install octryx-claude": the copy-paste one-liners for this platform (and the selected Workspace), the
// prerequisites and the served client version. The installers verify the package checksum shown here; Claude Code
// itself is a prerequisite they never install. Windows runs the client in WSL2 (Claude Code's sandbox).
export function AgentsInstallClient({ workspaceId, load = loadOctryxInstall }: {
  workspaceId: string | null;
  load?: (workspaceId: string | null) => Promise<unknown>;
}) {
  const [install, setInstall] = useState<OctryxInstall | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    setInstall(null);
    setProblem(null);
    load(workspaceId).then(
      (payload) => {
        if (!current) return;
        const read = readOctryxInstall(payload);
        if (read) setInstall(read);
        else setProblem("The server's answer did not contain usable install commands.");
      },
      (error: unknown) => { if (current) setProblem(installErrorText(error)); },
    );
    return () => { current = false; };
  }, [workspaceId, load]);

  if (problem) return <p className="work-area__error" role="alert" data-testid="agents-install-error">{problem}</p>;
  if (!install) return <p className="agents-area__hint" role="status">Loading install commands…</p>;
  return (
    <div className="agents-install" data-testid="agents-install">
      <p className="agents-area__hint">
        Run the line for the developer's operating system in a terminal. It installs octryx-claude into the user's home
        (no admin rights), checks the package against the checksum below and opens the browser login
        {workspaceId ? " with this Workspace preselected" : ""}. Plain <code>claude</code> and <code>~/.claude</code> stay untouched.
      </p>
      <section className="admin-panel__card agents-install__os">
        <div className="admin-panel__section-header"><h2 className="agents-area__section-title">macOS and Linux</h2></div>
        <CommandLine command={install.macos} testId="agents-install-macos" />
        <p className="agents-area__hint">Needs Claude Code, curl and Python {install.requiresPython.replace(">=", "")} or newer (or uv).</p>
      </section>
      <section className="admin-panel__card agents-install__os">
        <div className="admin-panel__section-header"><h2 className="agents-area__section-title">Windows (PowerShell)</h2></div>
        <CommandLine command={install.windows} testId="agents-install-windows" />
        <p className="agents-area__hint">
          Needs WSL2 with a Linux distribution (once, as administrator: <code>wsl --install</code>) and Claude Code inside it:
          governed sessions require Claude Code's sandbox, which runs on Windows only in WSL2.
        </p>
      </section>
      <section className="admin-panel__card agents-install__os">
        <div className="admin-panel__section-header"><h2 className="agents-area__section-title">Prerequisite: Claude Code</h2></div>
        <CommandLine command="curl -fsSL https://claude.ai/install.sh | bash" testId="agents-install-claude" />
        <p className="agents-area__hint">The official installer (macOS, Linux, WSL2). The octryx-claude installer checks for it and never installs it.</p>
      </section>
      <dl className="admin-panel__card agents-install__facts">
        <div><dt>Client version</dt><dd data-testid="agents-install-version">{install.version}</dd></div>
        <div><dt>Package sha256</dt><dd><CommandLine command={install.sha256} testId="agents-install-sha256" /></dd></div>
        <div><dt>Update</dt><dd><code>{macosCommand(install, "update")}</code> · <code>{windowsCommand(install, "update")}</code></dd></div>
        <div><dt>Uninstall</dt><dd><code>{macosCommand(install, "uninstall")}</code> · <code>{windowsCommand(install, "uninstall")}</code> (add <code>--purge</code> / <code>-Purge</code> to also revoke the login)</dd></div>
      </dl>
    </div>
  );
}

function CommandLine({ command, testId }: { command: string; testId: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // The command stays selectable when the clipboard is not available.
    }
  };
  return (
    <div className="agents-install__command">
      <code data-testid={testId}>{command}</code>
      <button type="button" className="admin-panel__action-btn" onClick={() => void copy()} data-testid={`${testId}-copy`}>{copied ? "Copied" : "Copy"}</button>
    </div>
  );
}
