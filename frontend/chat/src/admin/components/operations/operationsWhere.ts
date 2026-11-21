// Where a run or item works, in words: device or server, short folder and model.
import { modelDisplayName } from "../../../chat/header/runDetailsFacts";
import type { OpsDevice, OpsItem, OpsWhere } from "./operationsTypes";

/** Where a run or item works: the device (or the server), then the folder and the model. */
export function whereText(where: OpsWhere | null, devices: OpsDevice[] = []): { place: string; detail: string } {
  if (!where) return { place: "", detail: "" };
  const deviceName = where.deviceName || devices.find((device) => device.id === where.deviceId)?.name || "A device";
  const place = where.kind === "device"
    ? (where.online === false ? `${deviceName} (offline)` : deviceName)
    : where.kind === "terminal" ? where.label || "Terminal" : "Server";
  return { place, detail: [shortFolder(where.folder), where.model ? modelDisplayName(where.model) : ""].filter(Boolean).join(" · ") };
}

/** Where an item works: its job's folder and its model (".octryx-items/core-domain · Haiku 4.5"). */
export function itemWhereText(item: Pick<OpsItem, "model" | "job">): string {
  return [shortFolder(item.job?.folder ?? ""), item.model ? modelDisplayName(item.model) : ""].filter(Boolean).join(" · ");
}

/** A folder by its name ("kitchen-helper"); an item folder keeps its parent (".octryx-items/core-domain"). No home paths. */
export function shortFolder(folder: string): string {
  const parts = folder.split("/").filter(Boolean);
  if (parts.length < 2) return parts[0] ?? "";
  return parts[parts.length - 2].startsWith(".") ? parts.slice(-2).join("/") : parts[parts.length - 1];
}
