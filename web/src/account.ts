/** Google sign-in and the server copy of favorites (deploy/user-api).
    Two calls of our own API carry everything: GET /me and PUT /me/favorites.
    Google's button script is the only third-party code, injected on first need
    so the first load and offline use never pay for it. The user key is Google's
    `sub`, so the rows can move to any other backend without re-linking anyone. */

import { favoritesDirty, getFavorites, setFavorites } from "./favorites";
import { clearSession, profile, sessionToken, setSession, signedIn, type Profile } from "./session";

const API = (import.meta.env.VITE_USER_API as string | undefined) ?? "";
const CLIENT_ID = (import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined) ?? "";
const GSI_SRC = "https://accounts.google.com/gsi/client";
const GSI_TIMEOUT_MS = 8000;
const PUSH_DEBOUNCE_MS = 800;

/** Build has no API or client id (a data-only preview) - sign-in is not offered. */
export function accountSupported(): boolean {
  return API !== "" && CLIENT_ID !== "";
}

export class AccountError extends Error {
  constructor(
    public kind:
      | "offline"
      | "unreachable"
      | "google"
      | "blocked"
      | "popup-blocked"
      | "api"
      | "signed-out",
    message: string,
  ) {
    super(message);
  }
}

// ---- Google Identity Services ---------------------------------------------

let gsiLoad: Promise<GsiOauth2> | null = null;

/** The GIS `google.accounts.oauth2` namespace, loading the script on first call. */
export function loadGsi(): Promise<GsiOauth2> {
  const ready = window.google?.accounts?.oauth2;
  if (ready) return Promise.resolve(ready);
  if (gsiLoad) return gsiLoad;
  gsiLoad = new Promise<GsiOauth2>((resolve, reject) => {
    // A script that errors or loads without the namespace, on a device that is
    // online, is almost always a privacy / ad-blocking extension (Disconnect blocked
    // accounts.google.com on 2026-09-11) - say that, not "check your connection".
    // A timeout is Google being slow, which is the one case that message fits.
    const fail = (why: string) => {
      gsiLoad = null; // a later attempt (back online) starts fresh
      reject(new AccountError(why === "timeout" ? "google" : "blocked", why));
    };
    // this device has no connection at all - not something to blame Google for
    if (!navigator.onLine) {
      gsiLoad = null;
      return reject(new AccountError("offline", "offline"));
    }
    const s = document.createElement("script");
    s.src = GSI_SRC;
    s.async = true;
    s.defer = true;
    const timer = setTimeout(() => {
      s.remove();
      fail("timeout");
    }, GSI_TIMEOUT_MS);
    s.onload = () => {
      clearTimeout(timer);
      const o = window.google?.accounts?.oauth2;
      if (o) resolve(o);
      else fail("no gsi");
    };
    s.onerror = () => {
      clearTimeout(timer);
      s.remove();
      fail("load");
    };
    document.head.appendChild(s);
  });
  return gsiLoad;
}

/** Thrown when the user closed Google's popup or picked no account - not a failure. */
export class SignInCancelled extends Error {}

/** Open Google's account chooser (always - `select_account`, so a surfer with two
    Google accounts picks, instead of the last one being assumed), take the one-time
    code it returns and complete the sign-in through our API. Must be called from a
    user gesture (the popup is otherwise blocked). */
export async function startGoogleSignIn(): Promise<Profile> {
  const oauth2 = await loadGsi();
  const code = await new Promise<string>((resolve, reject) => {
    const client = oauth2.initCodeClient({
      client_id: CLIENT_ID,
      scope: "openid email profile",
      ux_mode: "popup",
      select_account: true,
      callback: (r) => {
        if (r.code) resolve(r.code);
        else if (r.error === "access_denied") reject(new SignInCancelled("denied"));
        else reject(new AccountError("google", r.error ?? "no code"));
      },
      error_callback: (e) => {
        if (e.type === "popup_closed") reject(new SignInCancelled("closed"));
        else if (e.type === "popup_failed_to_open") reject(new AccountError("popup-blocked", e.type));
        else reject(new AccountError("google", e.type));
      },
    });
    client.requestCode();
  });
  return signInWithCode(code);
}

// ---- our API ---------------------------------------------------------------

interface MeResponse {
  token?: string;
  profile: Profile;
  favorites: string[];
}

async function call<T>(path: string, init: RequestInit & { auth?: boolean } = {}): Promise<T> {
  if (!navigator.onLine) throw new AccountError("offline", "offline");
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (init.auth !== false) {
    const token = sessionToken();
    if (!token) throw new AccountError("signed-out", "no session");
    headers.Authorization = `Bearer ${token}`;
  }
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, { ...init, headers });
  } catch {
    // the browser is online but OUR api did not answer - never Google's fault,
    // and the message the user sees has to say so
    throw new AccountError("unreachable", "user api unreachable");
  }
  if (res.status === 401 && init.auth !== false) {
    // The session died server-side (signed out elsewhere, account deleted).
    // The local favorites cache stays - the next sign-in merges it back.
    clearSession();
    throw new AccountError("signed-out", "session expired");
  }
  if (!res.ok) throw new AccountError("api", `user api ${res.status}`);
  return (await res.json()) as T;
}

/** Exchange Google's one-time code for a Rosa session, then IMPORT this device's
    pre-account favorites into the account: the server list first, then anything
    local it did not have (this is how the ~100 pre-2026-09-07 users keep the
    favorites their browser held). One PUT, and from then on the server is the
    truth for every device. */
export async function signInWithCode(code: string): Promise<Profile> {
  const me = await call<MeResponse>("/auth/google", {
    method: "POST",
    auth: false,
    body: JSON.stringify({ code }),
  });
  if (!me.token) throw new AccountError("api", "no token");
  const local = getFavorites();
  const merged = [...me.favorites, ...local.filter((id) => !me.favorites.includes(id))];
  setSession(me.token, me.profile);
  if (merged.length !== me.favorites.length) {
    setFavorites(merged, { dirty: true });
    try {
      await pushFavorites();
    } catch {
      // stays dirty - syncFavorites() retries on the next launch / reconnect
    }
  } else {
    setFavorites(me.favorites);
  }
  void import("./push").then((m) => m.syncPushSpots()).catch(() => undefined);
  return me.profile;
}

/** Sign out everywhere: the server bumps the session epoch, so every device's
    token dies. Favorites leave this device with the account - they are the
    account's, and they are back on the next sign-in. */
export async function signOut(): Promise<void> {
  try {
    await call("/auth/logout", { method: "POST" });
  } catch {
    // offline or already dead - local sign-out still happens
  }
  clearSession();
  setFavorites([]);
  void import("./push").then((m) => m.syncPushSpots()).catch(() => undefined);
}

/** Delete the account and everything stored under it, then sign out locally. */
export async function deleteAccount(): Promise<void> {
  await call("/me", { method: "DELETE" });
  clearSession();
  setFavorites([]);
  void import("./push").then((m) => m.syncPushSpots()).catch(() => undefined);
}

async function pushFavorites(): Promise<void> {
  const list = getFavorites();
  const r = await call<{ favorites: string[] }>("/me/favorites", {
    method: "PUT",
    body: JSON.stringify({ favorites: list }),
  });
  // The server may have deduped; only rewrite the cache if it actually differs,
  // and only if no newer toggle landed while the request was in flight.
  const now = getFavorites();
  if (JSON.stringify(now) === JSON.stringify(list)) {
    if (JSON.stringify(r.favorites) !== JSON.stringify(list)) setFavorites(r.favorites);
    else localStorage.removeItem("rosa.favorites.dirty");
  }
}

let pushTimer: ReturnType<typeof setTimeout> | null = null;

/** Debounced PUT of the local list. Two quick toggles cost one request. */
export function scheduleFavoritesPush(): void {
  if (pushTimer) clearTimeout(pushTimer);
  pushTimer = setTimeout(() => {
    pushTimer = null;
    pushFavorites().catch(() => undefined); // stays dirty, retried by syncFavorites()
  }, PUSH_DEBOUNCE_MS);
}

/** Reconcile on launch and on reconnect: a dirty local list is pushed, otherwise
    the server list is pulled (another device may have changed it). Silent. */
export async function syncFavorites(): Promise<void> {
  if (!accountSupported() || !signedIn()) return;
  try {
    if (favoritesDirty()) {
      await pushFavorites();
      return;
    }
    const me = await call<MeResponse>("/me");
    if (JSON.stringify(me.favorites) !== JSON.stringify(getFavorites())) setFavorites(me.favorites);
    const p = profile();
    if (!p || p.name !== me.profile.name || p.picture !== me.profile.picture || p.email !== me.profile.email) {
      const token = sessionToken();
      if (token) setSession(token, me.profile);
    }
  } catch {
    // offline, or the session died (call() already cleared it) - nothing to do here
  }
}
