import { useCallback, useEffect, useRef, useState } from "react";
import {
  ACTIVE_WORKSPACE_EVENT,
  forgetWorkspacePreference,
  readStoredWorkspacePreference,
  readUrlWorkspaceId,
  resolveActiveWorkspaceId,
  setActiveWorkspaceUser,
  storeWorkspacePreference,
  type WorkspacePreference,
} from "./activeWorkspace";

type WorkspaceRef = { id: string; isDefault?: boolean; is_default?: boolean };

// The Instance's default workspace among the projects, if an administrator set one.
export function defaultWorkspaceIdOf(projects: WorkspaceRef[]): string {
  return projects.find((project) => project.isDefault || project.is_default)?.id || "";
}

// The Workspace the app may pick by itself while the person has made no choice (fresh-install review): the
// Instance's default, else the only one. With several and no default nothing is guessed; pages then offer the
// choice inline (ChooseWorkspaceLine).
export function automaticWorkspaceIdOf(projects: WorkspaceRef[]): string {
  return defaultWorkspaceIdOf(projects) || (projects.length === 1 ? projects[0].id : "");
}

function initialPreference(): WorkspacePreference {
  return readUrlWorkspaceId() || readStoredWorkspacePreference();
}

// The Workspace "New chat" starts in: the active Workspace (the address's workspace_id or the person's last choice,
// which the global switch sets), else the chat's own when it is an active one, else the default or the only one.
// The chat on screen can live in an archived Workspace (after a login the latest chat opens, wherever it is); a new
// chat never starts there. `projects` holds only active Workspaces. An explicit "no workspace" choice stays one
// where Global is allowed.
export function newChatWorkspaceId(projects: WorkspaceRef[], chatProjectId: string, allowGlobal = false): string {
  const known = (id: string | null | undefined) => Boolean(id) && projects.some((project) => project.id === id);
  const preference = initialPreference();
  if (preference === "" && allowGlobal) return "";
  if (preference && known(preference)) return preference;
  if (known(chatProjectId)) return chatProjectId;
  return automaticWorkspaceIdOf(projects);
}

// newChatWorkspaceId for the shell, current after a choice made anywhere (the global switch in another area does not
// otherwise re-render the chat shell).
export function useNewChatWorkspaceId(
  userId: string | null | undefined,
  projects: WorkspaceRef[],
  chatProjectId: string,
  allowGlobal = false,
): string {
  setActiveWorkspaceUser(userId);
  const [, setChoices] = useState(0);
  useEffect(() => {
    const onChange = () => setChoices((count) => count + 1);
    window.addEventListener(ACTIVE_WORKSPACE_EVENT, onChange);
    return () => window.removeEventListener(ACTIVE_WORKSPACE_EVENT, onChange);
  }, []);
  return newChatWorkspaceId(projects, chatProjectId, allowGlobal);
}

// Shared workspace selection for area pages. `fallbackId` is usually the chat's
// selected workspace and applies only while the user has no preference; without
// one, the Instance's default workspace is the starting point.
// Returns "" when nothing valid is known or the user chose no workspace, so
// callers show an explicit "Select a workspace" state instead of guessing.
export function useActiveWorkspace(projects: WorkspaceRef[], fallbackId?: string | null) {
  const [preference, setPreference] = useState<WorkspacePreference>(initialPreference);

  useEffect(() => {
    const onChange = (event: Event) => setPreference((event as CustomEvent<string>).detail ?? "");
    // Back/forward shows exactly what a fresh load of that history entry shows:
    // its workspace_id, or — without one — the user's last explicit choice.
    const onPopState = () => setPreference(initialPreference());
    window.addEventListener(ACTIVE_WORKSPACE_EVENT, onChange);
    window.addEventListener("popstate", onPopState);
    return () => {
      window.removeEventListener(ACTIVE_WORKSPACE_EVENT, onChange);
      window.removeEventListener("popstate", onPopState);
    };
  }, []);

  // The chat's workspace when it is known, else the default or the only Workspace. An explicit "no workspace"
  // choice ("") and a URL workspace_id always win (resolveActiveWorkspaceId).
  const knownFallback = fallbackId && projects.some((project) => project.id === fallbackId) ? fallbackId : "";
  const workspaceId = resolveActiveWorkspaceId(projects, preference, knownFallback || automaticWorkspaceIdOf(projects));
  const setWorkspaceId = useCallback((next: string) => {
    setPreference(next);
    storeWorkspacePreference(next);
  }, []);
  return [workspaceId, setWorkspaceId] as const;
}

// Keeps the chat composer's workspace and the shared active workspace aligned.
// The first value the chat bootstraps with does not overwrite an earlier
// explicit choice; later composer changes do. A choice made in another area
// moves a new (not yet started) chat along, never an existing session, and an
// explicit "no workspace" choice elsewhere leaves the chat untouched.
// One context for the whole app: an existing chat on screen is the context, so opening it
// (from a link or the list) makes its Workspace the active one; choosing another Workspace in the global switch
// while that chat is on screen leaves it for a new chat in the chosen Workspace (`onLeaveSession`).
export function useChatWorkspaceSync(
  userId: string | null | undefined,
  selectedProjectId: string,
  setSelectedProjectId: (projectId: string) => void,
  projects: WorkspaceRef[],
  hasSelectedSession: boolean,
  allowGlobalSelection = false,
  chatVisible = false,
  onLeaveSession?: (projectId: string) => void,
) {
  setActiveWorkspaceUser(userId);
  const bootstrapped = useRef(false);
  const previous = useRef(selectedProjectId);

  useEffect(() => {
    if (!projects.length || !userId) return;
    // `projects` holds only active Workspaces: the chat's Workspace can be an archived one (its latest session
    // lives there), and that one never becomes the active Workspace of the other areas.
    const known = (id: string) => projects.some((project) => project.id === id);
    if (!bootstrapped.current) {
      bootstrapped.current = true;
      previous.current = selectedProjectId;
      const preference = initialPreference();
      const stale = Boolean(preference) && !known(preference as string);
      const preferred = resolveActiveWorkspaceId(projects, preference, null);
      const explicitGlobal = preference === "" && allowGlobalSelection;
      if ((preferred || explicitGlobal) && preferred !== selectedProjectId && !hasSelectedSession) {
        setSelectedProjectId(preferred);
      } else if (stale) {
        // A choice (address or storage) for an archived Workspace is replaced by what every area shows instead: the
        // chat's Workspace when it is an active one, else the Instance's default (or the only one).
        const start = known(selectedProjectId) ? selectedProjectId : automaticWorkspaceIdOf(projects);
        if (start) storeWorkspacePreference(start);
        else forgetWorkspacePreference();
      } else if (preference === null && known(selectedProjectId)) storeWorkspacePreference(selectedProjectId);
      return;
    }
    if (selectedProjectId !== previous.current) {
      // An explicit Global/no-workspace choice in a new chat is a choice too
      // (judge J-A-004); switching to an existing session only moves along when
      // that session has a workspace, so its scope is never rewritten.
      const explicitNone = !selectedProjectId && !hasSelectedSession;
      if (((selectedProjectId && known(selectedProjectId)) || explicitNone)
        && selectedProjectId !== readStoredWorkspacePreference()) {
        storeWorkspacePreference(selectedProjectId);
      }
    }
    previous.current = selectedProjectId;
  }, [allowGlobalSelection, hasSelectedSession, projects, selectedProjectId, setSelectedProjectId, userId]);

  // The chat on screen is the context: its Workspace becomes the active one.
  useEffect(() => {
    if (!chatVisible || !hasSelectedSession || !selectedProjectId || !userId) return;
    if (!projects.some((project) => project.id === selectedProjectId)) return;
    if (readStoredWorkspacePreference() !== selectedProjectId) storeWorkspacePreference(selectedProjectId);
  }, [chatVisible, hasSelectedSession, projects, selectedProjectId, userId]);

  useEffect(() => {
    const onChange = (event: Event) => {
      const next = (event as CustomEvent<string>).detail || "";
      if (next && hasSelectedSession && chatVisible && onLeaveSession && next !== selectedProjectId
        && projects.some((project) => project.id === next)) {
        previous.current = next;
        onLeaveSession(next);
        return;
      }
      // "Global · no workspace" from the switch (administrators; the composer has no Workspace select of its own since
      // review): a new chat takes it; an open chat of a Workspace is left for a new chat without one.
      if (!next && allowGlobalSelection) {
        if (hasSelectedSession) {
          if (chatVisible && onLeaveSession && selectedProjectId) {
            previous.current = "";
            onLeaveSession("");
          }
          return;
        }
        if (selectedProjectId) {
          previous.current = "";
          setSelectedProjectId("");
        }
        return;
      }
      if (!next || hasSelectedSession || next === previous.current) return;
      if (projects.some((project) => project.id === next)) {
        previous.current = next;
        setSelectedProjectId(next);
      }
    };
    window.addEventListener(ACTIVE_WORKSPACE_EVENT, onChange);
    return () => window.removeEventListener(ACTIVE_WORKSPACE_EVENT, onChange);
  }, [allowGlobalSelection, chatVisible, hasSelectedSession, onLeaveSession, projects, selectedProjectId, setSelectedProjectId]);
}
