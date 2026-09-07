import { useEffect, useRef, useState } from "preact/hooks";
import { accountSupported } from "../account";
import { toggleFavorite } from "../favorites";
import { ACCOUNT_EVENT, SIGNIN_REQUEST_EVENT, signedIn } from "../session";
import { GoogleButton } from "./GoogleButton";
import { mountParticles } from "./particles";

const SEEN_KEY = "rosa.signin.seen"; // sessionStorage: "Not now" holds for this launch
const PENDING_KEY = "rosa.signin.pending"; // the spot tapped before signing in

/** The sign-in screen. Same look as the splash, so on a signed-out launch the
    splash lifts straight onto it (it mounts underneath at once: z 9998 vs 9999)
    and the app appears behind the moment the user answers. "Not now" keeps the
    forecast fully usable; only saving a spot asks again, through
    `requestSignIn(spotId)`, and that spot is saved the instant sign-in lands. */
export function SignInScreen() {
  const [open, setOpen] = useState<boolean>(() => {
    if (!accountSupported() || signedIn()) return false;
    try {
      return sessionStorage.getItem(SEEN_KEY) !== "1";
    } catch {
      return true;
    }
  });
  const particlesRef = useRef<HTMLCanvasElement>(null);

  const readPending = (): string | null => {
    try {
      return sessionStorage.getItem(PENDING_KEY);
    } catch {
      return null;
    }
  };
  const writePending = (id: string | null) => {
    try {
      if (id) sessionStorage.setItem(PENDING_KEY, id);
      else sessionStorage.removeItem(PENDING_KEY);
    } catch {
      // private mode - the toggle is simply not replayed
    }
  };

  // A toggle that was waiting on a sign-in completed on a previous page load
  // (the service worker reloads the page on an update) - apply it now.
  useEffect(() => {
    const pending = readPending();
    if (pending && signedIn()) {
      writePending(null);
      toggleFavorite(pending);
    }
  }, []);

  useEffect(() => {
    const onRequest = (e: Event) => {
      if (!accountSupported()) return;
      const id = (e as CustomEvent<{ pendingToggle: string | null }>).detail?.pendingToggle ?? null;
      writePending(id);
      setOpen(true);
    };
    const onAccount = (e: Event) => {
      // signed in from somewhere else (Profile card) - nothing left to ask
      if ((e as CustomEvent).detail) setOpen(false);
    };
    addEventListener(SIGNIN_REQUEST_EVENT, onRequest);
    addEventListener(ACCOUNT_EVENT, onAccount);
    return () => {
      removeEventListener(SIGNIN_REQUEST_EVENT, onRequest);
      removeEventListener(ACCOUNT_EVENT, onAccount);
    };
  }, []);

  const onDone = (err: Error | null) => {
    if (err) return; // the button shows the failure and its Retry
    const pending = readPending();
    writePending(null);
    if (pending) toggleFavorite(pending); // signed in now, so this saves
    setOpen(false);
  };

  // Same particle field the splash carries, so the hand-over is seamless.
  useEffect(() => {
    if (!open) return;
    const canvas = particlesRef.current;
    if (!canvas || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let handle: { stop(): void } | null = null;
    try {
      handle = mountParticles(canvas, {
        palette: ["125, 185, 240", "94, 205, 205"],
        density: 1.4,
        speed: 1,
        alpha: 0.3,
      });
    } catch {
      handle = null;
    }
    return () => handle?.stop();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  if (!open) return null;

  const later = () => {
    try {
      sessionStorage.setItem(SEEN_KEY, "1");
    } catch {
      // fine - it asks again next launch
    }
    writePending(null);
    setOpen(false);
  };

  return (
    <div class="signin-screen" role="dialog" aria-modal="true" aria-labelledby="signin-title">
      <div class="signin-glow" />
      <canvas ref={particlesRef} class="signin-particles" aria-hidden="true" />
      <div class="signin-inner">
        <div class="signin-mark" />
        <span class="signin-word">
          rosa<i class="signin-dot" />
        </span>
        <h2 id="signin-title" class="sr-only">Sign in</h2>
        <div class="signin-google">
          <GoogleButton size="large" width={280} onDone={onDone} />
        </div>
        <button class="signin-later" onClick={later}>
          Not now
        </button>
      </div>
    </div>
  );
}
