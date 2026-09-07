/** Who is signed in, on this device. The session token is Rosa's own (minted by
    deploy/user-api after it verified a Google credential); the profile is the
    name/email/picture the API returned beside it. Both live in localStorage so
    a relaunch is signed in without a round trip. Nothing here talks to the
    network - that is account.ts, which favorites.ts loads lazily. */

export interface Profile {
  sub: string; // Google's stable user id - the key everything is stored under
  email: string | null;
  name: string | null;
  picture: string | null;
}

const SESSION_KEY = "rosa.session";
const PROFILE_KEY = "rosa.profile";

/** Fired on window when sign-in state changes (detail: the new profile or null). */
export const ACCOUNT_EVENT = "rosa:account";
/** Fired on window when the favorites cache changed from OUTSIDE a toggle
    (a server sync, a sign-in merge, a sign-out) - pages re-read getFavorites(). */
export const FAVORITES_EVENT = "rosa:favorites";
/** Fired on window to open the sign-in screen (detail: {pendingToggle?: spotId}). */
export const SIGNIN_REQUEST_EVENT = "rosa:signin-request";

export function sessionToken(): string | null {
  try {
    return localStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

export function signedIn(): boolean {
  return sessionToken() !== null;
}

export function profile(): Profile | null {
  try {
    const raw = localStorage.getItem(PROFILE_KEY);
    const p: unknown = raw ? JSON.parse(raw) : null;
    return p && typeof p === "object" && typeof (p as Profile).sub === "string" ? (p as Profile) : null;
  } catch {
    return null;
  }
}

export function setSession(token: string, p: Profile): void {
  localStorage.setItem(SESSION_KEY, token);
  localStorage.setItem(PROFILE_KEY, JSON.stringify(p));
  dispatchEvent(new CustomEvent(ACCOUNT_EVENT, { detail: p }));
}

export function clearSession(): void {
  localStorage.removeItem(SESSION_KEY);
  localStorage.removeItem(PROFILE_KEY);
  dispatchEvent(new CustomEvent(ACCOUNT_EVENT, { detail: null }));
}

/** Ask the app to show the sign-in screen. `pendingToggle` is the spot the user
    just tried to favorite; it is applied the moment sign-in completes. */
export function requestSignIn(pendingToggle?: string): void {
  dispatchEvent(new CustomEvent(SIGNIN_REQUEST_EVENT, { detail: { pendingToggle: pendingToggle ?? null } }));
}
