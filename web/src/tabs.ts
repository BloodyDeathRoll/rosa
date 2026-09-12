export type Tab = "today" | "spots" | "map" | "charts" | "settings";

export const TAB_ROUTES: Record<Tab, string> = {
  today: "/",
  spots: "/spots",
  map: "/map",
  charts: "/charts",
  settings: "/settings",
};
