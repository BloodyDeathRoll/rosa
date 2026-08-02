import { useEffect, useState } from "preact/hooks";
import { installOffer, markInstallSeen, runInstall, type InstallOffer } from "../install";
import { appReady } from "../splash";

const AFTER_SPLASH_MS = 700; // the splash fades over 450ms - let it clear first
const SPLASH_CAP_MS = 10_000; // same safety net main.tsx uses to lift the splash

/** Add-to-home-screen sheet, offered until it is answered (see install.ts). Chromium
    gets a button wired to its own install dialog; browsers that can install but
    expose no API for it (iOS Safari, Firefox for Android) get the one sentence
    that says where their control lives. */
export function InstallPrompt() {
  const [offer, setOffer] = useState<InstallOffer | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let disposed = false;
    let armed = false; // stays false until the splash is gone

    const evaluate = () => {
      if (disposed || !armed) return;
      const next = installOffer();
      if (!next) return;
      setOffer(next); // marked seen only once the user answers it, not on sight
    };
    const onInstalled = () => {
      if (!disposed) setOffer(null);
    };

    // Chrome's offer often lands after mount; index.html re-broadcasts it
    addEventListener("rosa:installable", evaluate);
    addEventListener("appinstalled", onInstalled);

    const splashGone = Promise.race([
      appReady,
      new Promise<void>((r) => setTimeout(r, SPLASH_CAP_MS)),
    ]);
    void splashGone.then(() =>
      setTimeout(() => {
        armed = true;
        evaluate();
      }, AFTER_SPLASH_MS),
    );

    return () => {
      disposed = true;
      removeEventListener("rosa:installable", evaluate);
      removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  if (!offer) return null;

  const dismiss = () => {
    markInstallSeen(); // answered - a reload won't ask again
    setOffer(null);
  };
  const install = async () => {
    setBusy(true);
    await runInstall().catch(() => false); // user cancelled, or the offer went stale
    setBusy(false);
    dismiss();
  };

  return (
    <div class="install-wrap">
      <button class="install-scrim" aria-label="Not now" onClick={dismiss} />
      <section class="install-sheet" role="dialog" aria-labelledby="install-title">
        <img class="install-mark" src="/icon.svg" alt="" width="54" height="54" />
        <h2 id="install-title">Install Rosa</h2>
        {offer === "ios" ? (
          <p>
            Tap <b>Share</b> in Safari, then <b>Add to Home Screen</b>.
          </p>
        ) : offer === "firefox" ? (
          <p>
            Open Firefox's <b>menu</b>, then <b>Install</b> (older versions call it{" "}
            <b>Add to Home screen</b>).
          </p>
        ) : (
          <p>Opens full screen, starts faster, and keeps your last forecast readable offline.</p>
        )}
        <div class="install-actions">
          {offer !== "prompt" ? (
            <button class="install-go" onClick={dismiss}>
              Got it
            </button>
          ) : (
            <>
              <button class="install-later" onClick={dismiss}>
                Not now
              </button>
              <button class="install-go" disabled={busy} onClick={() => void install()}>
                Install
              </button>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
