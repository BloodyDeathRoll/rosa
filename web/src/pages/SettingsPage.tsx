import { useEffect, useState } from "preact/hooks";
import { ChevronRightIcon, MoonIcon, SunIcon } from "../components/icons";
import { AppHeader } from "../components/parts";
import { getFavorites } from "../favorites";
import { disablePush, enablePush, pushState, type PushState } from "../push";
import { signalReady } from "../splash";
import { setUnits, useUnits } from "../units";
import type { Theme } from "../theme";

/** Swell-alert opt-in/out — one obvious switch, helper text explains the state. */
function NotificationsCard() {
  const [state, setState] = useState<PushState | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    void pushState().then(setState);
  }, []);
  if (state === null) return null;

  const turnOn = async () => {
    setBusy(true);
    setFailed(false);
    try {
      setState(await enablePush());
    } catch {
      // permission granted but registering with the alert service failed —
      // say so instead of silently snapping back to Off
      setState("off");
      setFailed(true);
    }
    setBusy(false);
  };
  const turnOff = async () => {
    setBusy(true);
    setFailed(false);
    await disablePush().catch(() => undefined);
    setState("off");
    setBusy(false);
  };

  const note = failed
    ? "Couldn't reach the alert service — check your connection and try again."
    : state === "unsupported"
      ? "Not available in this browser. On iPhone, add Rosa to your home screen first."
      : state === "denied"
        ? "Notifications are blocked for Rosa in your browser settings — allow them there, then try again."
        : state === "on"
          ? "One heads-up when a new swell is on the way to your favorite spots. Never more than one per swell."
          : "Get a heads-up when a new swell is on the way to your favorite spots.";

  return (
    <section class="settings-card">
      <div class="card-title">
        <span class="eyebrow">Notifications</span>
      </div>
      <div class="settings-row">
        <span class="label">Swell alerts</span>
        <div class="segmented" role="radiogroup" aria-label="Swell alerts">
          <button
            role="radio"
            aria-checked={state === "on"}
            class={state === "on" ? "on" : ""}
            disabled={busy || state === "unsupported" || state === "denied"}
            onClick={() => void turnOn()}
          >
            On
          </button>
          <button
            role="radio"
            aria-checked={state !== "on"}
            class={state !== "on" ? "on" : ""}
            disabled={busy}
            onClick={() => void turnOff()}
          >
            Off
          </button>
        </div>
      </div>
      <p class="settings-note">{note}</p>
    </section>
  );
}

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

        <NotificationsCard />

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
          <button class="settings-row tall about-link" onClick={() => (location.hash = "#/about/how")}>
            <span class="label">How it works</span>
          </button>
          <button class="settings-row tall about-link" onClick={() => (location.hash = "#/about/terms")}>
            <span class="label">Terms of Use</span>
          </button>
          <button class="settings-row tall about-link" onClick={() => (location.hash = "#/about/privacy")}>
            <span class="label">Privacy Policy</span>
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
