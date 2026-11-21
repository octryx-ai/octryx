// The More tab's links: Macs, Seat, Operations, My role and the plugin phone pages of the Workspace.
import type { MobileTabScreenProps } from "./MobileTabScreen";

export function moreLinks(
  { devices, roleWorkspaceName, phonePages, openPage }: MobileTabScreenProps,
  onlineMacs: number,
) {
  return [
    {
      key: "macs",
      label: "Your Macs",
      detail: devices ? `${onlineMacs} of ${devices.length} online` : "Online state and running jobs",
      icon: "device" as const,
      onOpen: () => openPage({ kind: "devices" }),
    },
    {
      key: "seat",
      label: "Seat",
      detail: "Your own subscription and what the Workspace allows",
      icon: "card" as const,
      onOpen: () => openPage({ kind: "seat" }),
    },
    {
      key: "operations",
      label: "Operations",
      detail: "What runs where, and what is stuck",
      icon: "pulse" as const,
      onOpen: () => openPage({ kind: "operations" }),
    },
    {
      key: "role",
      label: "My role",
      detail: roleWorkspaceName ? `Roles and tools in ${roleWorkspaceName}` : "Roles and tools per Workspace",
      icon: "user" as const,
      onOpen: () => openPage({ kind: "role" }),
    },
    ...phonePages.map((page) => ({
      key: `plugin:${page.key}`,
      label: page.slot.title,
      detail: `${page.pluginName} · plugin`,
      icon: "stack" as const,
      onOpen: () => openPage({ kind: "plugin", key: page.key }),
    })),
  ];
}
