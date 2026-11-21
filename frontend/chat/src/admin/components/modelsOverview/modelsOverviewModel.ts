// Global › Models: every provider set up the same way (LiteLLM from the company gateway is a
// provider like Bedrock), the models a workspace can choose with their price, and what the workspaces made of each:
// the global level defines, a workspace only narrows. Data: GET /api/v1/admin/model-catalog/overview.

import { readJson } from "../../utils/adminPanelHelpers";
import type { StatusTone } from "../../../layout/StatusLabel";

export type OverviewProvider = {
  id: string;
  name: string;
  driver: string;
  endpoint: string | null;
  state: "connected" | "failing" | "off";
  error: string | null;
  models_found: number;
  models_on: number;
  loaded_at: string | null;
};

export type OverviewModel = {
  key: string;
  label: string;
  provider: string;
  price_in: number | null;
  price_out: number | null;
  cost_source: string | null;
  available_in: number;
  off_in: string[];
  default_in: string[];
  platform_default: boolean;
  provider_off?: boolean;
};

export type ModelsOverview = {
  providers: OverviewProvider[];
  models: OverviewModel[];
  workspaces: number;
  platform_default: string | null;
};

export const OVERVIEW_PATH = "/api/v1/admin/model-catalog/overview";
export const loadModelsOverview = (): Promise<ModelsOverview> => readJson<ModelsOverview>(OVERVIEW_PATH);

const STATE: Record<OverviewProvider["state"], { label: string; tone: StatusTone }> = {
  connected: { label: "Connected", tone: "success" },
  failing: { label: "Not reachable", tone: "problem" },
  off: { label: "Switched off", tone: "neutral" },
};

export function providerState(provider: OverviewProvider): { label: string; tone: StatusTone } {
  return STATE[provider.state] ?? STATE.connected;
}

/** "14 models found · 6 switched on"; an off provider says what that means instead. */
export function providerModelsLine(provider: OverviewProvider): string {
  if (provider.state === "off") return "Its models are not offered and not used as fallback.";
  if (!provider.models_found) return "No models loaded yet.";
  return `${provider.models_found} model${provider.models_found === 1 ? "" : "s"} found · ${provider.models_on} switched on`;
}

/** "$0.14 / $0.40" per 1M tokens, or null when the price is missing (the row then offers to set it). */
export function priceText(model: OverviewModel): string | null {
  if (model.price_in == null || model.price_out == null) return null;
  const usd = (value: number) => `$${value.toFixed(2)}`;
  return `${usd(model.price_in)} / ${usd(model.price_out)}`;
}

/** "All 5", "Selected: 2", "None". */
export function availableText(model: OverviewModel, workspaces: number): string {
  if (model.provider_off) return "Not offered: provider switched off";
  if (!workspaces) return "–";
  if (model.available_in >= workspaces) return `All ${workspaces}`;
  if (!model.available_in) return "None";
  return `Selected: ${model.available_in}`;
}

const quoted = (name: string) => `“${name}”`;

function names(list: string[]): string {
  return list.length <= 2 ? list.map(quoted).join(", ") : `${list.length} workspaces`;
}

/** What the workspaces changed: where it is their default, where they switched it off. */
export function workspaceChanges(model: OverviewModel): string {
  const parts: string[] = [];
  if (model.default_in.length) parts.push(`Default in ${names(model.default_in)}`);
  if (model.off_in.length) {
    parts.push(model.off_in.length === 1 ? `Off in ${quoted(model.off_in[0])}` : `Off in ${model.off_in.length} workspaces`);
  }
  return parts.join(" · ") || "none";
}
