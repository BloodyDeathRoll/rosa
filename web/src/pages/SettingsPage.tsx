import { useEffect } from "preact/hooks";
import { ChevronRightIcon, MoonIcon, SunIcon } from "../components/icons";
import { AppHeader } from "../components/parts";
import { getFavorites } from "../favorites";
import { signalReady } from "../splash";
import { setUnits, useUnits } from "../units";
import type { Theme } from "../theme";

export function SettingsPage({
  theme,
  onSetTheme,
}: {
  theme: Theme;
  onSetTheme: (t: Theme) => void;
}) {
  const units = useUnits();
  const favCount = getFavorites().length;
  const metric = units.height === "m";
  // no async data — ready as soon as it mounts (lets the splash lift promptly)
  useEffect(signalReady, []);

  return (
    <main class="page">
      <AppHeader right={<span class="head-note">profile</span>} />
      <div class="settings-page">
        <section class="settings-card">
          <div class="card-title">
            <span class="eyebrow">Preferences</span>
          </div>
          <div class="settings-row">
            <span class="label">Units</span>
            <div class="segmented" role="radiogroup" aria-label="Units">
              <button
                role="radio"
                aria-checked={metric}
                class={metric ? "on" : ""}
                onClick={() => setUnits({ height: "m", temp: "c" })}
              >
                m
              </button>
              <button
                role="radio"
                aria-checked={!metric}
                class={!metric ? "on" : ""}
                onClick={() => setUnits({ height: "ft", temp: "f" })}
              >
                ft
              </button>
            </div>
          </div>
          <div class="settings-row">
            <span class="label">Theme</span>
            <div class="segmented" role="radiogroup" aria-label="Theme">
              <button
                role="radio"
                aria-checked={theme === "light"}
                class={theme === "light" ? "on" : ""}
                onClick={() => onSetTheme("light")}
              >
                <SunIcon />
                Light
              </button>
              <button
                role="radio"
                aria-checked={theme === "dark"}
                class={theme === "dark" ? "on" : ""}
                onClick={() => onSetTheme("dark")}
              >
                <MoonIcon />
                Dark
              </button>
            </div>
          </div>
        </section>

        <section class="settings-card">
          <div class="card-title">
            <span class="eyebrow">Spots</span>
          </div>
          <div class="settings-row tall">
            <span class="label">Home region</span>
            <span class="value">
              Israel <ChevronRightIcon />
            </span>
          </div>
          <button class="settings-row tall" onClick={() => (location.hash = "#/spots")}>
            <span class="label">Favorites</span>
            <span class="value tabular">
              {favCount} {favCount === 1 ? "spot" : "spots"} <ChevronRightIcon />
            </span>
          </button>
        </section>

        <section class="settings-card">
          <div class="card-title">
            <span class="eyebrow">About Rosa</span>
          </div>
          <button class="settings-row tall" onClick={() => (location.hash = "#/about/how")}>
            <span class="label">How it works</span>
            <span class="value">
              <ChevronRightIcon />
            </span>
          </button>
          <button class="settings-row tall" onClick={() => (location.hash = "#/about/terms")}>
            <span class="label">Terms of Use</span>
            <span class="value">
              <ChevronRightIcon />
            </span>
          </button>
          <button class="settings-row tall" onClick={() => (location.hash = "#/about/privacy")}>
            <span class="label">Privacy Policy</span>
            <span class="value">
              <ChevronRightIcon />
            </span>
          </button>
        </section>

        <footer class="settings-foot">
          <p>rosa 0.1 · forecasts are estimates — surf with your own eyes</p>
          <p>Weather data by Open-Meteo.com (CC-BY 4.0)</p>
        </footer>
      </div>
    </main>
  );
}
