import type { ComponentProps } from "react";

import type { ThreadSummary } from "../chatThreadTypes";
import { AppContainerView } from "./AppContainerView";

type AppContainerViewProps = ComponentProps<typeof AppContainerView>;

type UseAppContainerViewPropsArgs = Omit<
  AppContainerViewProps,
  "handleArchiveThread" | "onApprovalStateChanged"
> & {
  handleArchiveThreadById: (
    threadId: string,
    archiveHandler: () => Promise<void>,
  ) => Promise<void>;
  handleArchive: () => Promise<void>;
};

export function useAppContainerViewProps({
  handleArchiveThreadById,
  handleArchive,
  ...viewProps
}: UseAppContainerViewPropsArgs): AppContainerViewProps {
  const handleArchiveThread = async (thread: ThreadSummary) => {
    await handleArchiveThreadById(thread.id, handleArchive);
  };

  const onApprovalStateChanged = (_sessionId: string | null) => {
    // Refresh is handled in AppContainerView when admin updates approvals for the active session.
  };

  return {
    ...viewProps,
    handleArchiveThread,
    onApprovalStateChanged,
  };
}
