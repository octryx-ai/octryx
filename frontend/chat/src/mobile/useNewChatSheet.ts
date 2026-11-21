// State of the phone's new chat sheet: Workspace, Mac or Server, folder, billing, turn options, message and status.
import { useEffect, useMemo, useState } from "react";
import { readDevice, type MyDevice } from "../chat/devices/devicesModel";
import {
  readDeviceRunsPolicy,
  type DeviceRunsPolicy,
} from "../chat/devices/deviceRunsPolicyModel";
import { loadDevices, loadPolicy } from "./mobileApi";
import { billingOptions, type Billing } from "./mobileDeviceChats";
import { SERVER_TARGET } from "./mobileTurnOptions";
import type { ServerOptions } from "./ServerOptionsBar";
import { useTurnOptions } from "./useTurnOptions";

export function useNewChatSheetState(initialProjectId: string) {
  const [projectId, setProjectId] = useState(initialProjectId);
  const [devices, setDevices] = useState<MyDevice[]>([]);
  const [deviceId, setDeviceId] = useState("");
  const [folder, setFolder] = useState("");
  const [turnOptions, setTurnOptions] = useTurnOptions(null);
  const [serverOptions, setServerOptions] = useState<ServerOptions>({
    runtimeTargetId: "",
    thinkingLevel: "light",
  });
  const [policy, setPolicy] = useState<DeviceRunsPolicy | null>(null);
  const [billing, setBilling] = useState<Billing>("governed");
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return {
    projectId, setProjectId, devices, setDevices, deviceId, setDeviceId, folder, setFolder, turnOptions,
    setTurnOptions, serverOptions, setServerOptions, policy, setPolicy, billing, setBilling, prompt, setPrompt, busy,
    setBusy, error, setError,
  };
}

export type NewChatSheetState = ReturnType<typeof useNewChatSheetState>;

// Loads the person's Macs and the Workspace's device policy; keeps folder and billing valid for the chosen Mac.
export function useNewChatTargets(state: NewChatSheetState) {
  const { setDevices, setDeviceId, setError, projectId, setPolicy, devices, deviceId, folder, setFolder } = state;
  const { billing, setBilling, policy } = state;
  useEffect(() => {
    loadDevices().then(
      (raw) => {
        const items = ((raw as { items?: unknown[] }).items ?? [])
          .map(readDevice)
          .filter(
            (device): device is MyDevice =>
              !!device && device.folders.length > 0,
          );
        items.sort((a, b) => Number(b.connected) - Number(a.connected));
        setDevices(items);
        setDeviceId((current) => current || items[0]?.id || SERVER_TARGET);
      },
      () => setError("Your Macs could not be loaded."),
    );
  }, [setDevices, setDeviceId, setError]);

  useEffect(() => {
    setPolicy(null);
    if (projectId)
      loadPolicy(projectId).then(
        (raw) => setPolicy(readDeviceRunsPolicy(raw)),
        () => setPolicy(null),
      );
  }, [projectId, setPolicy]);

  const device = devices.find((item) => item.id === deviceId) ?? null;
  const options = useMemo(
    () => billingOptions(device, policy),
    [device, policy],
  );
  useEffect(() => {
    if (device && !device.folders.includes(folder))
      setFolder(device.folders[0] ?? "");
  }, [device, folder, setFolder]);
  useEffect(() => {
    if (options.length && !options.includes(billing)) setBilling(options[0]);
  }, [options, billing, setBilling]);
  return { device, options };
}
