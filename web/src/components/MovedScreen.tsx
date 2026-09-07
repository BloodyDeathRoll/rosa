import { useEffect } from "preact/hooks";
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
export function MovedScreen() {
  useEffect(signalReady, []);
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
          The app now lives at <b>rosa.surf</b>. Open it there, add it to your home screen, then
          delete this one.
        </p>
        <div class="signin-google">
          <a class="google-btn google-btn-large moved-go" href={`${APP_ORIGIN}/#/settings`} target="_blank" rel="noopener">
            Open rosa.surf
          </a>
        </div>
      </div>
    </div>
  );
}
