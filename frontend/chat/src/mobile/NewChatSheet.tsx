// A new chat on one of the person's Macs (Workspace, Mac, folder from the Mac's own allowlist, billing, model, effort,
// permission mode) or on the Server (Workspace, model, thinking), then the first message.

import type { ProjectOption } from "../chatOptionTypes";
import { billingLabel, folderName, type Billing } from "./mobileDeviceChats";
import { SERVER_TARGET } from "./mobileTurnOptions";
import { MacTurnOptions, NewChatHeader, ServerFields } from "./NewChatSheetFields";
import { newChatBlocked, startNewChat } from "./newChatStart";
import { useNewChatSheetState, useNewChatTargets } from "./useNewChatSheet";

type Props = {
  projects: ProjectOption[];
  // The Workspace the chat starts in (the phone's Workspace choice, else the default); the person may change it.
  initialProjectId: string;
  onClose: () => void;
  onStarted: (
    sessionId: string,
    projectId: string,
    title: string,
    onServer: boolean,
  ) => void;
};

export function NewChatSheet({ projects, initialProjectId, onClose, onStarted }: Props) {
  const state = useNewChatSheetState(initialProjectId);
  const { projectId, setProjectId, devices, deviceId, setDeviceId, folder, setFolder, billing, setBilling } = state;
  const { prompt, setPrompt, busy, error } = state;
  const onServer = deviceId === SERVER_TARGET;
  const { device, options } = useNewChatTargets(state);
  const blocked = newChatBlocked(onServer, device, state.policy, options);
  const start = () => startNewChat(state, { onServer, device, blocked }, onStarted);

  return (
    <div className="m-sheet" role="dialog" aria-modal="true" aria-label="New chat">
      <NewChatHeader onClose={onClose} />
      <main className="m-body m-form">
        <label htmlFor="m-workspace">Workspace</label>
        <select id="m-workspace" value={projectId} onChange={(event) => setProjectId(event.target.value)}>
          {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
        </select>
        <label htmlFor="m-device">Run on</label>
        <select id="m-device" value={deviceId} onChange={(event) => setDeviceId(event.target.value)}>
          {devices.map((item) => (
            <option key={item.id} value={item.id}>{item.name}{item.connected ? "" : " (offline)"}</option>
          ))}
          <option value={SERVER_TARGET}>Octryx server</option>
        </select>
        {onServer ? <ServerFields state={state} /> : (
          <>
            <label htmlFor="m-folder">Folder</label>
            <select id="m-folder" value={folder} onChange={(event) => setFolder(event.target.value)}>
              {(device?.folders ?? []).map((path) => <option key={path} value={path}>{folderName(path)}</option>)}
            </select>
            <label htmlFor="m-billing">Billing</label>
            <select id="m-billing" value={billing} disabled={!options.length}
              onChange={(event) => setBilling(event.target.value as Billing)}>
              {options.map((option) => <option key={option} value={option}>{billingLabel(option)}</option>)}
            </select>
            <MacTurnOptions state={state} device={device} />
          </>
        )}
        <label htmlFor="m-prompt">Message</label>
        <textarea id="m-prompt" rows={4} value={prompt} onChange={(event) => setPrompt(event.target.value)} />
        {blocked && <p className="m-warn">{blocked}</p>}
        {error && <p className="m-error" role="alert">{error}</p>}
      </main>
      <footer className="m-compose">
        <button
          type="button"
          className="m-primary m-full"
          disabled={!prompt.trim() || busy || !!blocked}
          onClick={() => void start()}
        >
          Start on {onServer ? "the Server" : (device?.name ?? "your Mac")}
        </button>
      </footer>
    </div>
  );
}
