export type Theme = "dark" | "light";

const KEY = "rosa.theme";

export function initialTheme(): Theme {
  const fromUrl = new URLSearchParams(location.search).get("theme");
  if (fromUrl === "light" || fromUrl === "dark") return fromUrl;
  const stored = localStorage.getItem(KEY);
  if (stored === "light" || stored === "dark") return stored;
  // respect the OS; Rosa's default when it expresses no preference is dark
  return matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
}

export function saveTheme(theme: Theme): void {
  localStorage.setItem(KEY, theme);
}
