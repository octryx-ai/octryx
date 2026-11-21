// The Spec Studio's line icon paths (24 px grid): kept apart from the component so both stay fast-refresh friendly.

export const PATHS = {
  comment: "M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-7l-4 3v-3H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM8 9.5h8M8 12.5h5",
  zoom: "M10.5 16.5a6 6 0 1 0 0-12 6 6 0 0 0 0 12zM15 15l5 5M8 10.5h5M10.5 8v5",
  fit: "M4 9V5h4M20 9V5h-4M4 15v4h4M20 15v4h-4",
  desktop: "M4 5h16v11H4zM9 20h6M12 16v4",
  phone: "M8 3.5h8a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1v-15a1 1 0 0 1 1-1zM11 18h2",
  sun: "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4",
  moon: "M19.5 14.5A7.5 7.5 0 0 1 9.5 4.5a7.5 7.5 0 1 0 10 10z",
  check: "m5 12.5 4.5 4.5L19 7.5",
  x: "M6 6l12 12M18 6 6 18",
  warning: "M12 4 2.5 20h19zM12 10v4.5M12 17.5h.01",
  back: "m14.5 5.5-6.5 6.5 6.5 6.5",
  lock: "M6.5 11h11v9h-11zM8.5 11V8a3.5 3.5 0 0 1 7 0v3",
  home: "M4 10.5 12 4l8 6.5V19a1 1 0 0 1-1 1h-4.5v-5.5h-5V20H5a1 1 0 0 1-1-1z",
  bean: "M12 3.5c4 0 6.5 3.6 6.5 8.5s-2.5 8.5-6.5 8.5S5.5 16.9 5.5 12 8 3.5 12 3.5zM12 4c-2 2.5-2 5.5 0 8s2 5.5 0 8",
  cup: "M4 9h13v5a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5zM17 11h1.5a2.5 2.5 0 0 1 0 5H17M8 3v3M11 3v3M14 3v3",
  grinder: "M7 3.5h10l-1.5 5h-7zM6 8.5h12v5H6zM8 13.5l1 7h6l1-7M12 16.5h.01",
  drop: "M12 3.5s6 6.7 6 11a6 6 0 0 1-12 0c0-4.3 6-11 6-11z",
  sponge: "M4 8.5h16v9H4zM7 11.5h.01M11 13h.01M15 11.5h.01M9 15h.01M16 15h.01",
  more: "M5.5 12h.01M12 12h.01M18.5 12h.01",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8",
  image: "M4 5h16v14H4zM4 15l4.5-4.5 4 4 2.5-2.5L20 17M15.5 9.5h.01",
  plus: "M12 5v14M5 12h14",
} as const;

export type StudioIconName = keyof typeof PATHS;

export function isStudioIcon(name: string | undefined): name is StudioIconName {
  return Boolean(name) && Object.hasOwn(PATHS, name as string);
}
