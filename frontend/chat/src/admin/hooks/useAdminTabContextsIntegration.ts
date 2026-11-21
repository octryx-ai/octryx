type TabLoader = (tab: string) => Promise<void>;

export function buildWebhooksTabCtx(
  args: Record<string, unknown> & { loadTab: TabLoader },
) {
  const { loadTab, ...ctx } = args;
  return {
    ...ctx,
    reloadWebhooksTab: () => {
      void loadTab("webhooks");
    },
  };
}

export function buildChannelsTabCtx(
  args: Record<string, unknown> & { loadTab: TabLoader },
) {
  const { loadTab, ...ctx } = args;
  return {
    ...ctx,
    reloadChannelsTab: () => {
      void loadTab("channels");
    },
  };
}

export function buildMcpTabCtx(
  args: Record<string, unknown> & { loadTab: TabLoader },
) {
  const { loadTab, ...ctx } = args;
  return {
    ...ctx,
    loadMcpTab: () => {
      void loadTab("mcp");
    },
  };
}

export function buildTtsTabCtx(args: Record<string, unknown>) {
  return args;
}

export function buildBrandingTabCtx(args: Record<string, unknown>) {
  return args;
}
