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

export function defaultWorkspaceIdOf(projects: WorkspaceRef[]): string {
  return projects.find((project) => project.isDefault || project.is_default)?.id || "";
}

// With several Workspaces and no default nothing is guessed.
export function automaticWorkspaceIdOf(projects: WorkspaceRef[]): string {
  return defaultWorkspaceIdOf(projects) || (projects.length === 1 ? projects[0].id : "");
}

function initialPreference(): WorkspacePreference {
  return readUrlWorkspaceId() || readStoredWorkspacePreference();
}

// A new chat never starts in an archived Workspace, though the chat on screen can live in one.
export function newChatWorkspaceId(projects: WorkspaceRef[], chatProjectId: string, allowGlobal = false): string {
  const known = (id: string | null | undefined) => Boolean(id) && projects.some((project) => project.id === id);
  const preference = initialPreference();
  if (preference === "" && allowGlobal) return "";
  if (preference && known(preference)) return preference;
  if (known(chatProjectId)) return chatProjectId;
  return automaticWorkspaceIdOf(projects);
}

// The global switch in another area does not otherwise re-render the chat shell.
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

// Returns "" rather than guessing, so callers show an explicit "Select a workspace" state.
export function useActiveWorkspace(projects: WorkspaceRef[], fallbackId?: string | null) {
  const [preference, setPreference] = useState<WorkspacePreference>(initialPreference);

  useEffect(() => {
    const onChange = (event: Event) => setPreference((event as CustomEvent<string>).detail ?? "");
    const onPopState = () => setPreference(initialPreference());
    window.addEventListener(ACTIVE_WORKSPACE_EVENT, onChange);
    window.addEventListener("popstate", onPopState);
    return () => {
      window.removeEventListener(ACTIVE_WORKSPACE_EVENT, onChange);
      window.removeEventListener("popstate", onPopState);
    };
  }, []);

  const knownFallback = fallbackId && projects.some((project) => project.id === fallbackId) ? fallbackId : "";
  const workspaceId = resolveActiveWorkspaceId(projects, preference, knownFallback || automaticWorkspaceIdOf(projects));
  const setWorkspaceId = useCallback((next: string) => {
    setPreference(next);
    storeWorkspacePreference(next);
  }, []);
  return [workspaceId, setWorkspaceId] as const;
}

// The bootstrap's first value never overwrites an earlier explicit choice; a choice elsewhere moves only a new, unstarted chat.
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
    // projects holds only active Workspaces; an archived chat Workspace never becomes the active one elsewhere.
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
        const start = known(selectedProjectId) ? selectedProjectId : automaticWorkspaceIdOf(projects);
        if (start) storeWorkspacePreference(start);
        else forgetWorkspacePreference();
      } else if (preference === null && known(selectedProjectId)) storeWorkspacePreference(selectedProjectId);
      return;
    }
    if (selectedProjectId !== previous.current) {
      // An existing session moves along only when it has a workspace, so its scope is never rewritten.
      const explicitNone = !selectedProjectId && !hasSelectedSession;
      if (((selectedProjectId && known(selectedProjectId)) || explicitNone)
        && selectedProjectId !== readStoredWorkspacePreference()) {
        storeWorkspacePreference(selectedProjectId);
      }
    }
    previous.current = selectedProjectId;
  }, [allowGlobalSelection, hasSelectedSession, projects, selectedProjectId, setSelectedProjectId, userId]);

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
