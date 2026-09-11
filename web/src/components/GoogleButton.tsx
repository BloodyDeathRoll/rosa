import { useEffect, useState } from "preact/hooks";
import { loadGsi, SignInCancelled, startGoogleSignIn } from "../account";

/** "Continue with Google" - the one and only sign-in control: the sign-in screen,
    the Spots tab's empty state and the Profile > Account card all render this.
    Drawn by us to Google's branding spec (white pill, the G, the standard text),
    not by Google: their rendered button turns into "Continue as <last account>"
    and skips the account chooser, which loses anyone with two Google accounts.
    A tap opens Google's own chooser popup (`select_account`). `onDone(null)` fires
    when the whole sign-in landed (code -> our API -> imported favorites),
    `onDone(err)` when it did not; a closed popup is neither. Sign-in state itself
    reaches the app through session.ts events. */
export function GoogleButton({
  size = "large",
  width = 280,
  onDone,
}: {
  size?: "large" | "medium";
  width?: number;
  onDone?: (err: Error | null) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  // warm the script so the tap opens the popup at once (a popup opened after an
  // await is still inside the gesture, but a network round trip first is not)
  useEffect(() => {
    void loadGsi().catch(() => undefined);
  }, []);

  const go = async () => {
    if (busy) return;
    setBusy(true);
    setFailure(null);
    try {
      await startGoogleSignIn();
      onDone?.(null);
    } catch (e) {
      if (e instanceof SignInCancelled) {
        // the surfer closed the popup - nothing to say
      } else {
        // Each failure names its own fix: a blocking extension, the browser's pop-up
        // blocker, Google itself, this device's connection, and our own user API.
        const kind = (e as { kind?: string }).kind;
        const msg =
          kind === "blocked"
            ? "Google sign-in is blocked - a privacy or ad-blocking extension may be stopping it. Allow accounts.google.com on rosa.surf and try again."
            : kind === "popup-blocked"
              ? "Your browser blocked Google's sign-in window - allow pop-ups for rosa.surf and try again."
              : kind === "google"
                ? "Google didn't answer - try again in a moment."
                : kind === "offline"
              ? "You're offline - reconnect and try again."
              : kind === "unreachable"
                ? "Rosa couldn't be reached - try again in a moment."
                : "Sign-in didn't complete - try again.";
        setFailure(msg);
        onDone?.(e instanceof Error ? e : new Error(msg));
      }
    }
    setBusy(false);
  };

  return (
    <div class="google-btn-wrap">
      <button
        type="button"
        class={`google-btn google-btn-${size}`}
        style={{ width: `${width}px` }}
        disabled={busy}
        aria-busy={busy}
        onClick={() => void go()}
      >
        <svg class="google-btn-g" viewBox="0 0 48 48" aria-hidden="true">
          <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
          <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
          <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
          <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
        </svg>
        <span>{busy ? "Opening Google…" : "Continue with Google"}</span>
      </button>
      {failure && <span class="google-btn-status google-btn-failed">{failure}</span>}
    </div>
  );
}
