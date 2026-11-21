import { useEffect } from "react";
import type { Dispatch, SetStateAction } from "react";

type UseAppContainerEffectsArgs = {
  selectedSessionId: string | null;
  chatTheme: "dark" | "light";
  chatThemeStorageKey: string;
  setEditingMessage: Dispatch<
    SetStateAction<{ id: string; content: string } | null>
  >;
  setStatsOpen: Dispatch<SetStateAction<boolean>>;
};

export function useAppContainerEffects({
  selectedSessionId,
  chatTheme,
  chatThemeStorageKey,
  setEditingMessage,
  setStatsOpen,
}: UseAppContainerEffectsArgs) {
  useEffect(() => {
    setEditingMessage(null);
  }, [selectedSessionId, setEditingMessage]);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", chatTheme);
    window.localStorage.setItem(chatThemeStorageKey, chatTheme);
  }, [chatTheme, chatThemeStorageKey]);

  useEffect(() => {
    setStatsOpen(false);
  }, [selectedSessionId, setStatsOpen]);
}
