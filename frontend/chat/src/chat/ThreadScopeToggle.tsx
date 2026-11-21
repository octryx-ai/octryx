// The explicit switch between the active Workspace's chats and all chats (threadScope.ts).
export function ThreadScopeToggle({ allWorkspaces, hiddenChats, hiddenWorkspaces, workspaceName, onChange }: {
  allWorkspaces: boolean;
  hiddenChats: number;
  hiddenWorkspaces: number;
  workspaceName: string;
  onChange: (allWorkspaces: boolean) => void;
}) {
  if (!allWorkspaces && !hiddenWorkspaces) return null;
  const label = allWorkspaces
    ? `Only ${workspaceName || "this workspace"}`
    : `All workspaces · ${hiddenChats} more ${hiddenChats === 1 ? "chat" : "chats"}`;
  return (
    <button type="button" className="thread-scope__toggle" aria-pressed={allWorkspaces}
      data-testid="thread-scope-toggle" onClick={() => onChange(!allWorkspaces)}>
      {label}
    </button>
  );
}
