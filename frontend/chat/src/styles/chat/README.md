# Chat Style Modules

This folder stores the main chat UI style modules.

The modules are grouped by dominant responsibility and imported in a fixed order from `frontend/chat/src/styles/chat.css`.

## Module Order

- `theme-base.css`
  - theme tokens
  - global resets
  - shared light-theme overrides
  - loading state primitives

- `app-shell.css`
  - top-level app shell
  - app frame only

- `foundation-shell.css`
  - shell overlay primitives
  - shared shell icon sizing

- `sidebar-shell.css`
  - sidebar frame
  - brand chrome
  - sidebar navigation
  - thread search shell

- `thread-list-shell.css`
  - import entrypoint for thread-list styling

- `thread-list-scroll.css`
  - thread-list scrollbar styling
  - shared feed scrollbar selectors

- `thread-list-tree.css`
  - thread groups and tree rows
  - subtree and nested thread layout

- `thread-card.css`
  - thread card shell and title row
  - status, pin, and counter chips

- `thread-card-menu.css`
  - thread row action menu
  - menu trigger and danger item states

- `thread-card-checkbox.css`
  - thread selection checkbox control

- `workspace-shell.css`
  - top-level workspace frame
  - workspace header and metadata
  - workspace shell status chips

- `approvals-workspace.css`
  - import entrypoint for the approvals/workspace split

- `approvals-workspace/approval-center.css`
  - approval cards and approval center
  - turn diff summary

- `approvals-workspace/workspace-feed.css`
  - workspace feed
  - timeline and rename bar actions

- `approvals-workspace/workspace-sidepanel.css`
  - workspace sidepanel shell

- `approvals-workspace/stats-presentation.css`
  - stats panel

- `workspace-tree-errors.css`
  - workspace sidepanel tree
  - file and change rows
  - workspace error states

- `message-stream.css`
  - import entrypoint for message stream styling

- `message-stream-feedback.css`
  - message feedback actions
  - feedback compose panel

- `message-stream-layout.css`
  - message rows and avatars
  - assistant/user bubble layout

- `message-stream-reasoning.css`
  - reasoning/thinking cards
  - performance metrics cards
  - thinking indicator animation

- `message-stream-markdown.css`
  - markdown typography
  - code and table rendering

- `tool-inline.css`
  - inline tool cards
  - inline detail rows
  - inline execution stats

- `tool-artifacts.css`
  - tool artifact cards
  - grouped tool card base styles

- `artifact-preview.css`
  - import entrypoint for artifact preview styling

- `artifact-preview-shell.css`
  - artifact preview modal shell
  - header and metadata presentation

- `artifact-preview-layout.css`
  - tabs, office layout, and preview frame areas
  - stage and toolbar structure

- `artifact-preview-sidecar.css`
  - sidecar cards and metadata rows
  - action-mode blocks and action buttons

- `artifact-preview-content.css`
  - panel content lists and issue/empty states

- `knowledge-empty-state.css`
  - knowledge entry cards
  - workspace empty state

- `composer-shell.css`
  - composer shell frame
  - composer surface base

- `composer-controls.css`
  - composer textarea
  - composer pills
  - send button

- `trace-drawer.css`
  - trace drawer
  - turn diff presentation

- `turn-execution-summary.css`
  - per-turn execution status card under assistant messages
  - bounded execution section in the turn trace modal

- `chat-responsive.css`
  - chat shell responsive rules
  - artifact preview responsive adjustments

- `chat-compact-shell.css`
  - narrow-viewport chat workspace
  - compact header, scrollable turn-context chips, header overflow menu
  - phone composer surface and its options disclosure

- `admin-panel-core.css`
  - import entrypoint for admin panel styling

- `admin-panel-shell.css`
  - admin modal shell
  - sidebar/header/body layout and tabs

- `admin-panel-actions.css`
  - section headers and action buttons
  - hints, form labels, and icon controls

- `admin-panel-data.css`
  - table styles and badges
  - overview cards and empty states

- `admin-panel-connectors.css`
  - connector card list inside admin panel

- `connectors-admin-forms.css`
  - import entrypoint for connector and admin-form styling

- `connectors-admin-forms-cards.css`
  - connector cards
  - connector form field presentation

- `connectors-admin-forms-health.css`
  - connector health
  - connector detail and policy status areas

- `connectors-admin-forms-channel-cards.css`
  - channel and connector overview cards

- `connectors-admin-forms-layout.css`
  - import entrypoint for task/runtime/policy layouts

- `connectors-admin-tasks.css`
  - task forms and task-item rows
  - task-run table and status details

- `connectors-admin-runtime.css`
  - runtime navigation and runtime list cards
  - provider/model priority controls

- `connectors-admin-policy-layout.css`
  - policy and config form layouts
  - policy summary grid and editor panel layout

- `admin-policy-modals.css`
  - import entrypoint for policy and modal styling

- `admin-policy-modals/modal-layout.css`
  - admin modal layouts
  - trace modal presentation

- `admin-policy-modals/policy-editors.css`
  - policy and admin editor surfaces

- `admin-policy-modals/policy-cards.css`
  - policy cards and related admin card surfaces

- `admin-policy-modals/provider-cards.css`
  - provider cards
  - device flow and provider-control surfaces

- `admin-provider-task-controls.css`
  - provider filters
  - task step list
  - runtime tags

- `composer-overlays.css`
  - composer autocomplete popup
  - composer notices
  - composer attachment chips

- `canvas-sidebar-profile.css`
  - canvas panel
  - sidebar bulk actions
  - sidebar profile dropdown

- `workspace-message-tooling.css`
  - workspace virtualization tweaks
  - resume notice
  - message action buttons
  - grouped tool follow-up actions

- `responsive-tts-diagram.css`
  - import entrypoint for TTS and diagram styling

- `responsive-tts-diagram-core.css`
  - import entrypoint for shared TTS/diagram admin surfaces

- `responsive-tts-diagram-usage.css`
  - usage panel and runtime performance
  - connector form textarea

- `responsive-tts-diagram-mcp-corp-identity.css`
  - MCP list and card presentation
  - corporate identity list and detail views

- `responsive-tts-diagram-toggle-controls.css`
  - toggle switches

- `responsive-tts-diagram-tts-ui.css`
  - TTS UI

- `responsive-tts-diagram-viewer.css`
  - diagram viewer

- `responsive-tts-diagram-responsive.css`
  - shared responsive rules for TTS and diagram areas

## Rules

- keep import order stable unless there is a clear cascade reason to change it
- add new rules to the closest responsible module
- do not reintroduce numeric part files
- if a module grows too broad, split it by responsibility with a descriptive name
