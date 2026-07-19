export type Tab = "home" | "map" | "favorites" | "account";

const KEY = "rosa.lastTab";
export const TAB_ROUTES: Record<Tab, string> = {
  home: "#/",
  map: "#/map",
  favorites: "#/favorites",
  account: "#/account",
};

export function saveLastTab(tab: Tab): void {
  localStorage.setItem(KEY, tab);
}

export function lastTab(): Tab {
  const t = localStorage.getItem(KEY);
  return t === "map" || t === "favorites" || t === "account" ? t : "home";
}
