export type Tab = "today" | "spots" | "map" | "settings";

const KEY = "rosa.lastTab";
export const TAB_ROUTES: Record<Tab, string> = {
  today: "#/",
  spots: "#/spots",
  map: "#/map",
  settings: "#/settings",
};

export function saveLastTab(tab: Tab): void {
  localStorage.setItem(KEY, tab);
}

export function lastTab(): Tab {
  const t = localStorage.getItem(KEY);
  if (t === "spots" || t === "map" || t === "settings") return t;
  if (t === "favorites") return "spots"; // pre-handoff tab name
  return "today";
}
