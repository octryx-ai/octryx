// The Model pill of a device job (model picker, backend services/devices/device_models.py): the rows
// octryx-claude's `/model` offers for the chosen profile in this Workspace, read defensively. The rows carry the
// catalog's display name; a bare id is never shown (`readableModelName`). An empty choice is the device's default.

import { readableModelName } from "./modelNames";

export type DeviceModelOption = { id: string; label: string; source: string; description: string };
export type DeviceModels = { profile: string; models: DeviceModelOption[]; reason: string | null };

const text = (value: unknown): string => (typeof value === "string" ? value : "");

export function readDeviceModels(raw: unknown): DeviceModels | null {
  if (!raw || typeof raw !== "object") return null;
  const item = raw as Record<string, unknown>;
  if (!text(item.profile) || !Array.isArray(item.models)) return null;
  const models = item.models.flatMap((row): DeviceModelOption[] => {
    const value = row && typeof row === "object" ? (row as Record<string, unknown>) : {};
    const id = text(value.id);
    const name = text(value.display_name);
    return id ? [{ id, label: name && name !== id ? name : readableModelName(id), source: text(value.source), description: text(value.description) }] : [];
  });
  return { profile: text(item.profile), models, reason: text(item.reason) || null };
}

/** The choice to keep when the rows change: the current one while it is still offered, else the device default. */
export function keptModel(current: string | undefined, rows: DeviceModels | null): string {
  if (!current) return "";
  if (!rows) return current;
  return rows.models.some((model) => model.id === current) ? current : "";
}

export function modelPillText(current: string | undefined, rows: DeviceModels | null): string {
  if (!current) return "Model: device default";
  return `Model: ${rows?.models.find((model) => model.id === current)?.label ?? readableModelName(current)}`;
}
