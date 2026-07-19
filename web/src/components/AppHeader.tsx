import type { Theme } from "../theme";
import { MoonIcon, SearchIcon, SunIcon } from "./icons";

export function AppHeader({
  theme,
  onToggleTheme,
}: {
  theme: Theme;
  onToggleTheme: () => void;
}) {
  return (
    <header class="app-head">
      <span class="brand">Rosa</span>
      <span class="head-actions">
        <a class="icon-btn" href="#/search" aria-label="Search spots">
          <SearchIcon />
        </a>
        <button
          class="icon-btn"
          onClick={onToggleTheme}
          aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          {theme === "dark" ? <SunIcon /> : <MoonIcon />}
        </button>
      </span>
    </header>
  );
}
