export type Theme = "dark" | "light";

const KEY = "rosa.theme";

export function initialTheme(): Theme {
  const fromUrl = new URLSearchParams(location.search).get("theme");
  if (fromUrl === "light" || fromUrl === "dark") return fromUrl;
  const stored = localStorage.getItem(KEY);
  if (stored === "light" || stored === "dark") return stored;
  // Rosa defaults to light (user decision 2026-07-20); Settings stores an override
  return "light";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
}

export function saveTheme(theme: Theme): void {
  localStorage.setItem(KEY, theme);
}
