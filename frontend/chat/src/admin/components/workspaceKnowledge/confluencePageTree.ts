// Confluence page-tree scope (confluence-page-tree-scope). Pure: no requests, no React.
//
// A page tree is a root page and every page below it: `{ space_key, root_page_id }` in the connector scope's
// `page_trees` (backend sync/confluence_scope.py). The server takes only the plain values and never reads a URL,
// so the author pastes a page address here and the space key and page id are taken from it visibly: the extracted
// values are shown and added only by an explicit "Add page tree". Nothing pasted is rewritten.
//
// Addresses read:
// - Confluence Cloud (and Data Center 8+):  …/wiki/spaces/KEY/pages/ID/Title   or   …/spaces/KEY/pages/ID
// - Data Center / Server:                   …/pages/viewpage.action?pageId=ID   (no space key: the author enters it)

export type PageTree = { space_key: string; root_page_id: string };

export const MAX_PAGE_TREES = 20;
export const SPACE_KEY = /^~?[A-Za-z0-9_]{1,64}$/;
export const ROOT_PAGE_ID = /^[0-9]{1,20}$/;

const SPACES_PAGE = /\/spaces\/(~?[A-Za-z0-9_]{1,64})\/pages\/(?:edit-v2\/)?([0-9]{1,20})(?:[/?#]|$)/;
const SPACE_ONLY = /\/spaces\/(~?[A-Za-z0-9_]{1,64})(?:[/?#]|$)/;
const DISPLAY_PAGE = /\/display\/(~?[A-Za-z0-9_]{1,64})\//;

export type PageAddress =
  | { kind: "empty" }
  | { kind: "page"; spaceKey: string | null; rootPageId: string }
  | { kind: "problem"; text: string };

/** What a pasted page address names: its page id and (when the address carries it) its space key. */
export function readPageAddress(value: string): PageAddress {
  const text = value.trim();
  if (!text) return { kind: "empty" };
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    return {
      kind: "problem",
      text: "Paste the full page address, starting with https://.",
    };
  }
  if (url.protocol !== "https:" && url.protocol !== "http:")
    return { kind: "problem", text: "Paste a web address of the page (https://…)." };
  const path = url.pathname;
  const spaced = SPACES_PAGE.exec(path);
  if (spaced) return { kind: "page", spaceKey: spaced[1], rootPageId: spaced[2] };
  if (/\/viewpage\.action$/.test(path)) {
    const pageId = url.searchParams.get("pageId") ?? "";
    if (!ROOT_PAGE_ID.test(pageId))
      return {
        kind: "problem",
        text: "This address names the page by its title, not its id. In Confluence open ••• → Page information and paste that address (…viewpage.action?pageId=…).",
      };
    const spaceKey = url.searchParams.get("spaceKey");
    return {
      kind: "page",
      spaceKey: spaceKey && SPACE_KEY.test(spaceKey) ? spaceKey : null,
      rootPageId: pageId,
    };
  }
  if (DISPLAY_PAGE.test(path))
    return {
      kind: "problem",
      text: "This address names the page by its title, not its id. In Confluence open ••• → Page information and paste that address (…viewpage.action?pageId=…).",
    };
  if (SPACE_ONLY.test(path))
    return {
      kind: "problem",
      text: "This is the address of a whole space, not of a page. Choose “Whole spaces” for it, or open the root page and paste its address.",
    };
  if (/\/wiki\/x\//.test(path))
    return {
      kind: "problem",
      text: "A short link (…/wiki/x/…) does not show the page id. Open the page and paste the address from the browser bar.",
    };
  return {
    kind: "problem",
    text: "No page id was found in this address. Paste the address of the page itself (…/spaces/KEY/pages/ID/… or …viewpage.action?pageId=ID).",
  };
}

/** The tree to add from a read address and the typed space key (used only when the address has none). */
export function pageTreeToAdd(
  address: PageAddress,
  typedSpaceKey: string,
): { tree: PageTree } | { problem: string } | null {
  if (address.kind !== "page") return null;
  const spaceKey = address.spaceKey ?? typedSpaceKey.trim();
  if (!spaceKey)
    return { problem: "This address does not show the space: enter the space key of the page." };
  if (!SPACE_KEY.test(spaceKey))
    return { problem: `“${spaceKey}” is not a valid Confluence space key.` };
  return { tree: { space_key: spaceKey, root_page_id: address.rootPageId } };
}

/** Why the trees cannot be saved as they are, or null. The server checks the same and stays the authority. */
export function pageTreesProblem(
  trees: readonly PageTree[],
  wholeSpaces: readonly string[],
): string | null {
  if (!trees.length) return "Add at least one page tree, or choose “Whole spaces”.";
  if (trees.length > MAX_PAGE_TREES) return `Add at most ${MAX_PAGE_TREES} page trees.`;
  const seen = new Set<string>();
  // Space keys compare case-insensitively, as the server does (confluence_scope.py: `.upper()`).
  const whole = new Set(wholeSpaces.map((space) => space.toUpperCase()));
  for (const tree of trees) {
    if (!SPACE_KEY.test(tree.space_key) || !ROOT_PAGE_ID.test(tree.root_page_id))
      return `The page tree ${tree.space_key} · ${tree.root_page_id} is not a space key and page id.`;
    if (seen.has(tree.root_page_id))
      return `The root page ${tree.root_page_id} is listed twice.`;
    seen.add(tree.root_page_id);
    if (whole.has(tree.space_key.toUpperCase()))
      return `The space ${tree.space_key} is already synced whole, so its page tree ${tree.root_page_id} would be listed twice: remove the tree or the space.`;
  }
  return null;
}

/** The stored trees of a connector scope, read strictly (anything else is left out, never guessed). */
export function storedPageTrees(scope: { page_trees?: unknown }): PageTree[] {
  if (!Array.isArray(scope.page_trees)) return [];
  return scope.page_trees.flatMap((tree) =>
    tree &&
    typeof tree === "object" &&
    typeof (tree as PageTree).space_key === "string" &&
    typeof (tree as PageTree).root_page_id === "string"
      ? [
          {
            space_key: (tree as PageTree).space_key,
            root_page_id: (tree as PageTree).root_page_id,
          },
        ]
      : [],
  );
}

// The server's refusal codes for page trees (sync/confluence_scope.py InvalidPageTreeError), as plain English.
export const PAGE_TREE_REASON_TEXT: Record<string, string> = {
  page_trees_invalid:
    "the page trees are not a list of space keys and root page ids (at most 20)",
  page_tree_space_invalid: "a page tree's space key is not a valid Confluence space key",
  page_tree_root_invalid:
    "a page tree's root page id is not a page id (the page's number, up to 20 digits)",
  page_tree_duplicate: "the same root page is listed twice",
  page_tree_in_listed_space:
    "a page tree is in a space the connector already syncs whole; remove the tree or the space",
  page_trees_confluence_only: "page trees are only for Confluence connectors",
};
