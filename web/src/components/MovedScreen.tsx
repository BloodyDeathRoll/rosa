import { useEffect } from "preact/hooks";
import { getFavorites } from "../favorites";
import { signalReady } from "../splash";

export const APP_ORIGIN = "https://rosa.surf";
const LEGACY_HOSTS = new Set(["rosa-rust.vercel.app"]);

/** Running from the old origin (an app installed before the 2026-09-06 move)? */
export function onLegacyOrigin(): boolean {
  return LEGACY_HOSTS.has(location.hostname);
}

/** What an app installed from the OLD origin shows instead of the forecast, once
    it has updated to this build. Until 2026-09-07 those apps could never update
    (their update check hit the redirect); the old host now serves the app files
    again - only real navigations redirect - so they update to THIS, which sends
    the surfer to rosa.surf to install afresh. Same look as the splash it lifts
    from. Nothing else in the app runs on the old origin. */
/** The link to the new origin. Storage is per origin, so the favorites this
    device kept under the old address ride along in the hash and main.tsx on
    rosa.surf imports them on arrival (`?import=`), before the sign-in screen
    asks for the account they will then be saved to. */
export function movedLink(): string {
  const favs = getFavorites();
  const q = favs.length ? `?import=${encodeURIComponent(favs.join(","))}` : "";
  return `${APP_ORIGIN}/#/spots${q}`;
}

export function MovedScreen() {
  useEffect(signalReady, []);
  const n = getFavorites().length;
  return (
    <div class="signin-screen" role="dialog" aria-labelledby="moved-title">
      <div class="signin-glow" />
      <div class="signin-inner">
        <div class="signin-mark" />
        <span class="signin-word">
          rosa<i class="signin-dot" />
        </span>
        <h2 id="moved-title">Rosa has moved</h2>
        <p>
          The app now lives at <b>rosa.surf</b>. Open it there, sign in
          {n > 0 ? ` to keep your ${n} saved ${n === 1 ? "spot" : "spots"}` : ""}, add it to your home
          screen, then delete this one.
        </p>
        <div class="signin-google">
          <a class="google-btn google-btn-large moved-go" href={movedLink()} target="_blank" rel="noopener">
            Open rosa.surf
          </a>
        </div>
      </div>
    </div>
  );
}
