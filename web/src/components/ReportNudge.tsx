import { useEffect, useState } from "preact/hooks";
import { markNudgeShown, nudgeDue, nudgeDueOnSignIn } from "../nudge";
import { lockScroll } from "../scroller";
import { ACCOUNT_EVENT } from "../session";
import { appReady } from "../splash";
import { XIcon } from "./icons";

const AFTER_SPLASH_MS = 700; // the splash fades over 450ms - let it clear first
const SPLASH_CAP_MS = 10_000; // same safety net main.tsx uses to lift the splash

/** Full-screen note that spots can be reported from the spot page (schedule in
    nudge.ts). Painted opaque like the report page - a translucent overlay lets
    the forecast bleed through. Sits one step under the install sheet and the
    sign-in screen, so on a first launch those are answered first and this is
    waiting underneath. X and OK both just close it. */
export function ReportNudge() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let disposed = false;

    const splashGone = Promise.race([
      appReady,
      new Promise<void>((r) => setTimeout(r, SPLASH_CAP_MS)),
    ]);
    void splashGone.then(() =>
      setTimeout(() => {
        if (disposed || !nudgeDue()) return;
        markNudgeShown("launch");
        setOpen(true);
      }, AFTER_SPLASH_MS),
    );

    const onAccount = (e: Event) => {
      if (disposed || !(e as CustomEvent).detail) return; // a sign-out
      if (!nudgeDueOnSignIn()) return;
      markNudgeShown("signin");
      setOpen(true);
    };
    addEventListener(ACCOUNT_EVENT, onAccount);
    return () => {
      disposed = true;
      removeEventListener(ACCOUNT_EVENT, onAccount);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    return lockScroll();
  }, [open]);

  if (!open) return null;

  const close = () => setOpen(false);

  return (
    <main class="nudge-page" role="dialog" aria-modal="true" aria-labelledby="nudge-title">
      <div class="nudge-inner">
        <button class="nudge-close" onClick={close} aria-label="Close">
          <XIcon size={24} />
        </button>
        <div class="nudge-body">
          <h1 id="nudge-title" class="nudge-title">
            Know a spot better than we do?
          </h1>
          <p class="nudge-lead">
            Check your favorites.
            <br />
            Wrong pin, wrong name, missing break? Tap <b>Report an issue</b> on the spot.
          </p>
          <p class="nudge-lead">A person reads every one.</p>
        </div>
        <div class="nudge-foot">
          <button class="nudge-ok" onClick={close}>
            OK
          </button>
        </div>
      </div>
    </main>
  );
}
