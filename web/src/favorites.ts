import { useEffect, useState } from "preact/hooks";
import { FAVORITES_EVENT, requestSignIn, signedIn } from "./session";

/** Favorites need an account (since 2026-09-07): the server copy is the truth,
    and `rosa.favorites` is this device's cache of the signed-in user's list, so
    a cleared browser costs nothing - sign in again and the list is back. Every
    reader (Today, Spots, feedback, push) keeps calling getFavorites(); only the
    writer changed: signed out, a toggle opens the sign-in screen instead of
    saving, and signed in, it saves locally at once and pushes to the server on
    a short debounce (account.ts), retrying on the next launch if that failed. */

const KEY = "rosa.favorites";
const DIRTY_KEY = "rosa.favorites.dirty"; // "1" = local list not yet confirmed by the server

export function getFavorites(): string[] {
  try {
    const raw = localStorage.getItem(KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

/** Overwrite the cache (a server sync, a sign-in merge, a sign-out) and tell
    every mounted page. Not for toggles - those go through toggleFavorite. */
export function setFavorites(list: string[], opts: { dirty?: boolean } = {}): void {
  localStorage.setItem(KEY, JSON.stringify(list));
  if (opts.dirty) localStorage.setItem(DIRTY_KEY, "1");
  else localStorage.removeItem(DIRTY_KEY);
  dispatchEvent(new CustomEvent(FAVORITES_EVENT));
}

export function favoritesDirty(): boolean {
  try {
    return localStorage.getItem(DIRTY_KEY) === "1";
  } catch {
    return false;
  }
}

export function toggleFavorite(id: string): string[] {
  const current = getFavorites();
  if (!signedIn()) {
    // Ask first; the screen re-runs this toggle once the account exists.
    requestSignIn(id);
    return current;
  }
  const next = current.includes(id) ? current.filter((x) => x !== id) : [...current, id];
  localStorage.setItem(KEY, JSON.stringify(next));
  localStorage.setItem(DIRTY_KEY, "1");
  // server copy + push alerts follow favorites; dynamic imports avoid load-time cycles
  void import("./account").then((m) => m.scheduleFavoritesPush()).catch(() => undefined);
  void import("./push").then((m) => m.syncPushSpots()).catch(() => undefined);
  return next;
}

/** Favorites as page state: the list, and a toggle that updates it. Re-reads the
    cache when it changes from outside a toggle (sign-in merge, server sync). */
export function useFavorites(): [string[], (id: string) => void] {
  const [favs, setFavs] = useState<string[]>(getFavorites);
  useEffect(() => {
    const onChange = () => setFavs(getFavorites());
    addEventListener(FAVORITES_EVENT, onChange);
    return () => removeEventListener(FAVORITES_EVENT, onChange);
  }, []);
  return [favs, (id: string) => setFavs(toggleFavorite(id))];
}
