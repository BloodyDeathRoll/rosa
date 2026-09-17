import { useEffect, useState } from "preact/hooks";
import { detectPlayApp, duplicateNoteDue, markDuplicateSeen } from "../install";
import { appReady } from "../splash";
import { removeHint } from "./MovedScreen";

const AFTER_SPLASH_MS = 700; // same beat as the install sheet

/** Shown once in a Chrome-installed PWA on a phone that also has the Play app:
    the two are the same Rosa (one origin, one sign-in), so this icon is the spare
    and only the user can remove it (see install.ts). Same sheet as the install
    offer it is the mirror of. */
export function DuplicateNote() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    let disposed = false;
    void Promise.all([detectPlayApp(), appReady]).then(() =>
      setTimeout(() => {
        if (!disposed && duplicateNoteDue()) setShow(true);
      }, AFTER_SPLASH_MS),
    );
    return () => {
      disposed = true;
    };
  }, []);

  if (!show) return null;

  const dismiss = () => {
    markDuplicateSeen();
    setShow(false);
  };

  return (
    <div class="install-wrap">
      <button class="install-scrim" aria-label="Got it" onClick={dismiss} />
      <section class="install-sheet" role="dialog" aria-labelledby="duplicate-title">
        <img class="install-mark" src="/icon.svg" alt="" width="54" height="54" />
        <h2 id="duplicate-title">You have Rosa twice</h2>
        <p>
          The Google Play app is on this phone too, with the same account and spots. {removeHint()}
        </p>
        <div class="install-actions">
          <button class="install-go" onClick={dismiss}>
            Got it
          </button>
        </div>
      </section>
    </div>
  );
}
