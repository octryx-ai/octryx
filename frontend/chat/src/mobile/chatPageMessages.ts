// The messages of a mobile chat as the page shows them, read from the chat API.

export type Message = {
  id: string;
  role: string;
  content: string;
  createdAt?: string;
};

export const readMessages = (raw: unknown[]): Message[] =>
  raw
    .map((item) => item as Record<string, unknown>)
    .filter(
      (item) => typeof item.id === "string" && typeof item.content === "string",
    )
    .map((item) => ({
      id: String(item.id),
      role: String(item.role || ""),
      content: String(item.content),
      createdAt:
        typeof item.created_at === "string" ? item.created_at : undefined,
    }));
