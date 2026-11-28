import { modelDisplayName } from "../../../chat/header/runDetailsFacts";
import type { OpsDevice, OpsItem, OpsWhere } from "./operationsTypes";

export function whereText(where: OpsWhere | null, devices: OpsDevice[] = []): { place: string; detail: string } {
  if (!where) return { place: "", detail: "" };
  const deviceName = where.deviceName || devices.find((device) => device.id === where.deviceId)?.name || "A device";
  const place = where.kind === "device"
    ? (where.online === false ? `${deviceName} (offline)` : deviceName)
    : where.kind === "terminal" ? where.label || "Terminal" : "Server";
  return { place, detail: [shortFolder(where.folder), where.model ? modelDisplayName(where.model) : ""].filter(Boolean).join(" · ") };
}

export function itemWhereText(item: Pick<OpsItem, "model" | "job">): string {
  return [shortFolder(item.job?.folder ?? ""), item.model ? modelDisplayName(item.model) : ""].filter(Boolean).join(" · ");
}

export function shortFolder(folder: string): string {
  const parts = folder.split("/").filter(Boolean);
  if (parts.length < 2) return parts[0] ?? "";
  return parts[parts.length - 2].startsWith(".") ? parts.slice(-2).join("/") : parts[parts.length - 1];
}
