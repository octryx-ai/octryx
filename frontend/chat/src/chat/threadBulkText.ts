// Counted nouns in the thread bulk controls: "1 chat", "3 chats".
export function plural(count: number, one: string, many: string) {
  return `${count} ${count === 1 ? one : many}`;
}
