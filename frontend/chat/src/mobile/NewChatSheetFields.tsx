// Parts of the phone's new chat sheet: its header, the Server's model and thinking, and a Mac's turn options.
import type { MyDevice } from "../chat/devices/devicesModel";
import { Icon } from "./icons";
import { ServerOptionsBar } from "./ServerOptionsBar";
import { TurnOptionsBar } from "./TurnOptionsBar";
import type { NewChatSheetState } from "./useNewChatSheet";

export function ServerFields({ state }: { state: NewChatSheetState }) {
  const { projectId, serverOptions, setServerOptions } = state;
  return (
    <>
      <label>Model and thinking</label>
      <ServerOptionsBar
        projectId={projectId}
        options={serverOptions}
        onChange={(patch) =>
          setServerOptions((current) => ({ ...current, ...patch }))
        }
      />
    </>
  );
}

export function MacTurnOptions({ state, device }: { state: NewChatSheetState; device: MyDevice | null }) {
  const { billing, turnOptions, setTurnOptions, projectId } = state;
  return (
    <>
      <label>Model, effort and permissions</label>
      <TurnOptionsBar
        options={turnOptions}
        onChange={setTurnOptions}
        projectId={projectId}
        profile={billing}
        deviceId={device?.id ?? ""}
      />
    </>
  );
}

export function NewChatHeader({ onClose }: { onClose: () => void }) {
  return (
    <header className="m-top">
      <button
        type="button"
        className="m-icon-button"
        aria-label="Close"
        onClick={onClose}
      >
        <Icon name="close" size={20} />
      </button>
      <div className="m-top-text">
        <strong>New chat</strong>
      </div>
    </header>
  );
}
