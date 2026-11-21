import { AttachIcon } from "./composerIcons";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";

import { formatBytes } from "./composerShellHelpers";
import type { DraftAttachment } from "./useComposerInteractions.types";

type EnhancementProps = {
  fileInputRef: MutableRefObject<HTMLInputElement | null>;
  uploadDraftFiles: (files: FileList | File[]) => Promise<void>;
  slashCommand: { open: boolean; query: string };
  slashCommands: Array<{ name: string; description: string }>;
  setComposerValue: Dispatch<SetStateAction<string>>;
  setSlashCommand: Dispatch<SetStateAction<{ open: boolean; query: string }>>;
  handleSend: (overridePrompt?: string) => Promise<void>;
  atMention: { open: boolean; query: string };
  groupedAgentOptions: Array<{
    label: string;
    agents: Array<{ id: string; name: string; description?: string }>;
  }>;
  handleSelectAtAgent: (agent: { id: string; name: string }) => void;
  draftAttachments: DraftAttachment[];
  uploadingAttachments: boolean;
  removeDraftAttachment: (attachmentId: string) => void;
};

export function ComposerInputEnhancements({
  fileInputRef, uploadDraftFiles, slashCommand, slashCommands, setComposerValue, setSlashCommand, handleSend, atMention,
  groupedAgentOptions, handleSelectAtAgent, draftAttachments, uploadingAttachments, removeDraftAttachment,
}: EnhancementProps) {
  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        multiple
        hidden
        onChange={(event) => {
          if (event.target.files?.length) {
            void uploadDraftFiles(event.target.files);
          }
        }}
      />
      {slashCommand.open ? (
        <SlashCommandPopup slashCommand={slashCommand} slashCommands={slashCommands} setComposerValue={setComposerValue}
          setSlashCommand={setSlashCommand} handleSend={handleSend} />
      ) : null}
      {atMention.open && groupedAgentOptions.length > 0 ? (
        <AgentMentionPopup groupedAgentOptions={groupedAgentOptions} handleSelectAtAgent={handleSelectAtAgent} />
      ) : null}
      {draftAttachments.length > 0 || uploadingAttachments ? (
        <DraftAttachmentList draftAttachments={draftAttachments} uploadingAttachments={uploadingAttachments}
          removeDraftAttachment={removeDraftAttachment} />
      ) : null}
    </>
  );
}

function SlashCommandPopup({ slashCommand, slashCommands, setComposerValue, setSlashCommand, handleSend }:
  Pick<EnhancementProps, "slashCommand" | "slashCommands" | "setComposerValue" | "setSlashCommand" | "handleSend">) {
  const filteredSlashCommands = slashCommands.filter((command) =>
    command.name.startsWith(slashCommand.query),
  );
  return (
    <div className="composer-popup composer-popup--command">
      <div className="composer-popup__header">
        <span className="composer-popup__title">Commands</span>
        <span className="composer-popup__hint">Run directly</span>
      </div>
      {filteredSlashCommands.length > 0 ? (
        filteredSlashCommands.map((command) => (
          <button
            key={command.name}
            type="button"
            className="composer-popup__item"
            onMouseDown={(event) => {
              event.preventDefault();
              setComposerValue("");
              setSlashCommand({ open: false, query: "" });
              void handleSend(`/${command.name}`);
            }}
          >
            <span className="composer-popup__name">/{command.name}</span>
            <span className="composer-popup__desc">
              {command.description}
            </span>
          </button>
        ))
      ) : (
        <div className="composer-popup__empty">
          <span className="composer-popup__title">No command matches</span>
          <span className="composer-popup__hint">
            Try a different slash keyword.
          </span>
        </div>
      )}
    </div>
  );
}

function AgentMentionPopup({ groupedAgentOptions, handleSelectAtAgent }:
  Pick<EnhancementProps, "groupedAgentOptions" | "handleSelectAtAgent">) {
  return (
    <div className="composer-popup composer-popup--mention">
      <div className="composer-popup__header">
        <span className="composer-popup__title">Agents</span>
        <span className="composer-popup__hint">Mention in message</span>
      </div>
      {groupedAgentOptions.map((group) => (
        <div key={group.label} className="composer-popup__group">
          <div className="composer-popup__group-label">{group.label}</div>
          {group.agents.map((agent) => (
            <button
              key={agent.id}
              type="button"
              className="composer-popup__item"
              onMouseDown={(event) => {
                event.preventDefault();
                handleSelectAtAgent(agent);
              }}
            >
              <span className="composer-popup__name">@{agent.name}</span>
              {agent.description ? (
                <span className="composer-popup__desc">
                  {agent.description}
                </span>
              ) : null}
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}

function DraftAttachmentList({ draftAttachments, uploadingAttachments, removeDraftAttachment }:
  Pick<EnhancementProps, "draftAttachments" | "uploadingAttachments" | "removeDraftAttachment">) {
  return (
    <div className="composer-attachments" aria-live="polite">
      <div className="composer-attachments__header">
        <span className="composer-attachments__label">
          <AttachIcon />
          <span>Attachments</span>
        </span>
        {draftAttachments.length > 0 ? (
          <span className="composer-attachments__count">
            {draftAttachments.length}
          </span>
        ) : null}
      </div>
      <div className="composer-attachments__list">
        {draftAttachments.map((attachment) => (
          <div key={attachment.id} className="composer-attachment-chip">
            <span className="composer-attachment-chip__icon">
              <AttachIcon />
            </span>
            <a
              href={attachment.url}
              target="_blank"
              rel="noreferrer"
              className="composer-attachment-chip__label"
            >
              <span>{attachment.name}</span>
              <small>{formatBytes(attachment.sizeBytes)}</small>
            </a>
            <button
              type="button"
              className="composer-attachment-chip__remove"
              title={`Remove ${attachment.name}`}
              onClick={() => removeDraftAttachment(attachment.id)}
            >
              Remove
            </button>
          </div>
        ))}
        {uploadingAttachments ? (
          <div className="composer-attachment-chip composer-attachment-chip--status">
            Uploading attachments…
          </div>
        ) : null}
      </div>
    </div>
  );
}
