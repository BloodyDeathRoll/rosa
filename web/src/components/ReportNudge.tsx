import { useEffect, useState } from "preact/hooks";
import { markNudgeShown, nudgeDue, nudgeDueOnSignIn } from "../nudge";
import { ACCOUNT_EVENT } from "../session";
import { appReady } from "../splash";
import { XIcon } from "./icons";

const AFTER_SPLASH_MS = 700; // the splash fades over 450ms - let it clear first
const SPLASH_CAP_MS = 10_000; // same safety net main.tsx uses to lift the splash
const DISMISS_MS = 9_000; // long enough to read twice, short enough to ignore

/** A drop-in note that spots can be reported from the spot page (schedule
    unchanged, in nudge.ts). It used to be a full-screen page, which on a phone
    stood between you and the forecast you opened the app for - so it now reads
    as one line in the same card language as the "Surfed it yesterday?" row,
    drops in over the top of whatever screen you are on, and leaves by itself.
    Sits one step under the install sheet and the sign-in screen, so on a first
    launch those are answered first and this arrives after them. */
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

  // A notification leaves on its own; the X is for whoever wants it gone now.
  // No scroll lock any more - the page underneath stays usable while it shows.
  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => setOpen(false), DISMISS_MS);
    return () => clearTimeout(t);
  }, [open]);

  if (!open) return null;

  return (
    <div class="nudge-drop" role="status">
      <span class="nudge-drop-text">
        <b>Spot look wrong?</b>
        <small>
          Tap <b>Report an issue</b> on the spot.
        </small>
      </span>
      <button class="nudge-drop-close" onClick={() => setOpen(false)} aria-label="Dismiss">
        <XIcon size={16} />
      </button>
    </div>
  );
}
