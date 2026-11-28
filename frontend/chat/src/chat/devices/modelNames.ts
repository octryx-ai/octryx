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
