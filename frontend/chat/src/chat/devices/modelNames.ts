// A person's name for a device model id, never the raw id ("Model: claude-opus-5-5"). The platform's rows
// carry the model catalog's display name (backend services/devices/device_models.subscription_model_names); this is
// the same rule for an id no row names yet (rows not loaded, a model the profile no longer offers, the job header):
// "claude-opus-5-5" -> "Claude Opus 5.5", "claude-haiku-4-5-20251001" -> "Claude Haiku 4.5". Another shape stays.

const ACRONYMS: Record<string, string> = { gpt: "GPT" };

const MODEL_ID = /^[a-z][a-z0-9.]*(?:-[a-z0-9.]+)*$/;

export function readableModelName(modelId: string): string {
  if (!MODEL_ID.test(modelId)) return modelId;
  const words: string[] = [];
  let version: string[] = [];
  for (const part of modelId.split("-")) {
    if (/^\d+$/.test(part)) {
      if (part.length < 8) version.push(part); // 8+ digits: a release date
      continue;
    }
    if (version.length) {
      words.push(version.join("."));
      version = [];
    }
    // "gpt-5.5-codex" (a Codex job's model) -> "GPT 5.5 Codex", not "Gpt".
    words.push(ACRONYMS[part] ?? part.charAt(0).toUpperCase() + part.slice(1));
  }
  if (version.length) words.push(version.join("."));
  return words.join(" ");
}
