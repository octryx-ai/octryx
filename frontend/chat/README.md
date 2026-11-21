# Octryx AI web app (frontend/chat)

The web app of Octryx AI: chat, work, knowledge, agents and workflows, operations, admin, and the phone app
(`src/mobile/`). React + TypeScript, built with Vite; the API serves the built bundle from
`backend/app/web/static/chat/`.

## Develop and test

```bash
npm ci
npm run dev          # Vite dev server
npx tsc --noEmit -p .
npx eslint src tests --quiet
npm test             # unit tests (node --test, tests/unit)
npm run test:e2e     # build, then every Playwright spec against a local backend
```

Before a pull request, run tsc, eslint and the unit tests (see CONTRIBUTING.md); run the Playwright specs when you
change a page they cover.

The help panel's pages (`help/<area>/<page>.md`) and the guides (`guides/`) are product content: the app shows
them. Write them for the person using the page.

## Principles

| | Principle | Meaning |
|---|---|---|
| P1 | Calm surfaces | Borders and gentle elevation instead of shadows. Gradients only as atmosphere, never as content colour. |
| P2 | Accent is meaning | The accent marks focus, route, in flow. Green only means "active". Never swap them. |
| P3 | Side panel, not modal | Create and edit always open a side panel. A modal dialog only for a pure confirmation. |
| P4 | Lists are tables | Data is a table, not a wall of cards. A card only for an element with an icon, a hierarchy and more than three values. |
| P5 | Global and Workspace apart | Credentials and definitions are global; assignment and use are per Workspace. The UI shows the difference. |

Tone: direct, technical and short; no marketing words, no exclamation marks. Buttons are imperatives ("Save
changes", "Publish"). Sentence case in headings. English throughout: UI, help, docs and specs.

Colours, brand and the full component catalogue: the design guide in the wiki
(<https://octryx.ai/docs/contribute/design-guide>). The values themselves live only in the code:
`src/styles/chat/ds-tokens.css`, `src/styles/chat/ui-set.css` and `src/styles/chat/theme-base.css`.

## Design system: the shared blocks

Every block is a plain `.ts` file in `src/layout/` built with `createElement` (pages and the unit-test loaders can
load it); its props are documented in the file. Styles: `src/styles/chat/design-system.css`; tokens:
`src/styles/chat/ds-tokens.css`. All follow the dark default and `[data-theme="light"]` through the theme variables.

1. **Lists are tables** (`DataTable`): full width, 36 px rows, a sticky header. Headers read the same everywhere:
   sentence case, small, weight 600, muted, never uppercase. ↑/↓ move, Home/End jump, Enter or Space opens a row.
2. **Details open in a side panel** (`SidePanel`) over the dimmed list, with tabs and "Open as page". Escape, ✕ or a
   click on the list closes it; focus stays inside and returns to the row. A form deep inside puts its actions into
   the panel footer (`PanelFooterActions`).
3. **One tab style** (`SegmentedTabs`), at most two levels: the page's views, then one small row of a view's pages.
   `tests/unit/designSystemTabs.test.mjs` fails on any other tab-like control (exceptions with a reason in its
   allowlist).
4. **One state label** (`StatusLabel`). Colour only for exceptions: neutral for every normal state, attention when a
   person must act, problem when something failed, success for a result worth noticing, info while in progress
   (`statusTone(state)` maps the common state words).
5. **Forms only in a side panel**, built from `FormSection`s, expert fields in a collapsed `AdvancedSection`. Every
   field has a visible label. "Add …" / "New …" opens the panel; its footer holds Cancel and the primary action,
   right-aligned, primary last. No inline create form on a list.
6. **An empty state is one line** with at most one action (`EmptyLine`), no box.
7. **A page carries no explanatory text**: at most one purpose sentence in the `PageHeader`, the rest in the help
   panel ("?"). The open help never covers the page; on a phone it is a sheet over the lower half.
8. **Pages use the full width**; only running text is limited, to about 72 characters.

## UI set: sizes and shapes

Every page, desktop and phone, is built from one set. The values live in `src/styles/chat/ds-tokens.css`, the shared
component shapes in `src/styles/chat/ui-set.css` (loaded last on desktop and phone). A value outside the set is a bug.

| What | Tokens | Values |
|---|---|---|
| Type | `--ds-text-2xs … 3xl` | 11 · 12 · 13 · 14 · 16 · 18 · 22 · 28 px |
| Weight | `--ds-weight-regular / medium / strong` | 400 · 500 · 600 (nothing in between, no 700+) |
| Spacing | `--ds-space-1 … 10` | multiples of 4 px: 4 · 8 · 12 · 16 · 20 · 24 · 32 · 40 |
| Radius | `--ds-radius-sm / md / lg / xl / pill` | 4 · 8 · 12 · 16 · pill |
| Control height | `--ds-control-sm / md / lg / touch` | 28 · 32 · 40 · 44 px |
| Icon | `--ds-icon-sm / md / lg` | 14 · 16 · 20 px |

| Element | Size | Weight | Notes |
|---|---|---|---|
| Page title (desktop and phone) | 22 (`2xl`) | 600 | one per page, `PageHeader` / `.m-page-title` |
| Eyebrow, group labels | 11 (`2xs`) | 600 | uppercase, tracking `--ds-tracking-caps` |
| Page purpose line | 13 (`sm`) | 400 | muted |
| Section title (panel, form section) | 16 (`lg`) | 600 | |
| Card title | 14 (`md`) | 600 | |
| UI text, table cells, buttons, inputs | 13 (`sm`) | 400 / 500 | |
| Meta, table header, badges, hints | 12 (`xs`) | 400 / 500 | muted |
| Chat and document prose | 14–16 | 400 | reading column only |
| Big numbers (KPI) | 28 (`3xl`) | 600 | |

Components:

- **Button**: height 32, radius 8, padding 0 12, text 13/500; primary 13/600 in the accent colour, one per view.
  In table rows and cards 28 high, text 12. Icon buttons are square. On the phone every tap target is 44. Pills only
  for filter chips and the phone's floating action.
- **Input and select**: the same height, radius and text as a button.
- **Card**: border `--border`, radius 12, padding 16, background `--panel-strong`; title 14/600, meta 12 muted.
- **Table** (`.ds-table`): header 12/500 muted, cells 13, rows 36, radius 8 around the table.
- **Status** (`.ds-status`): height 20, radius 4, text 12/500.
- **Page header**: eyebrow, title, purpose; on the right the Workspace switch, neutral actions, the one primary
  action and "?", always in this order.
- **Empty state** (`.ds-empty`): one sentence 13 muted, at most one action.
- **KPI tile** (`.ds-kpi`): a card with the number 28/600 and the label 12 muted.
- **Choice group** (`ChoiceGroup`): a value choice as toggle buttons with `aria-pressed`, in the look of small
  `SegmentedTabs`. Tabs switch panels; a choice sets a value.
- **Side panel** (`.ds-panel`): the only overlay on desktop; the phone uses sheets with radius 16.

Rules for new code:

1. A token, never a literal size: `font-size: var(--ds-text-sm)`, `border-radius: var(--ds-radius-md)`, spacing in
   multiples of 4 px.
2. The existing block (`PageHeader`, `DataTable`, `StatusLabel`, `EmptyLine`, `SidePanel`, `.ds-btn`, `.ds-card`)
   before a new one; no new button family, extend `.ds-btn`.
3. Colours from the theme variables in `src/styles/chat/theme-base.css` (they switch with light mode); no raw hex.
4. A preview of a product's own design (the Spec Studio mock) uses that product's tokens only and carries
   `data-ds-audit="skip"`; the controls around it stay on this set.

The CSS modules and their load order: `src/styles/chat/README.md`.

## Browser keys and events

Browser-only preferences use these keys: `octryx.composer.prefill.v1`, `octryx.chat.allWorkspaces.v1.<user>`,
`octryx.setup.skipped.v1.<user>`, `octryx.work.scope.<workspace>`, `octryx.runbar.open.<run>` and
`octryx.mobile.turnOptions:<thread-or-new>`.

DOM event names are `octryx:area-tab`, `octryx:artifact-draft`, `octryx:turn-execution-refresh` and
`octryx:open-page-help`.
