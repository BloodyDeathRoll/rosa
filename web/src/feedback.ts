/** Next-open retro feedback (v0.2 calibration loop): viewing a spot's forecast
    stashes that day's promise locally; the NEXT day's first open asks one tap -
    "was the call right?" - and ships {spot, at, predicted, verdict} to the
    feedback API. Nothing is ever asked in the moment, max one prompt per WEEK,
    only about GOOD-or-better days, and only for the favorite spot closest to
    the user's current location. Gated by the Profile "Spot feedback" toggle. */

import { fetchIndex } from "./api";
import { getFavorites } from "./favorites";
import { splitName, todayIn } from "./format";
import { distanceKm, getHome, getPosition } from "./geo";
import type { SpotPayload } from "./types";

const API = (import.meta.env.VITE_USER_API as string | undefined) ?? ""; // rosa-push via the user API's /push/feedback relay
const VIEWS_KEY = "rosa.fb.views";
const PREF_KEY = "rosa.fb.pref"; // "on" (default) | "off"
const LAST_KEY = "rosa.fb.last"; // ms epoch of the last resolved prompt
const KEEP_DAYS = 7;
const WEEK_MS = 7 * 86_400_000; // one ask a week, answered or dismissed alike

interface StashedView {
  spot: string;
  name: string;
  at: string; // best hour's spot-local ISO - the session being graded
  predicted: { rating: number; bucket: string; h: [number, number]; phrase?: string };
  done?: boolean;
}

export function feedbackPref(): boolean {
  return localStorage.getItem(PREF_KEY) !== "off";
}

export function setFeedbackPref(on: boolean): void {
  localStorage.setItem(PREF_KEY, on ? "on" : "off");
}

function readViews(): Record<string, StashedView> {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(VIEWS_KEY) ?? "{}");
    return parsed && typeof parsed === "object" ? (parsed as Record<string, StashedView>) : {};
  } catch {
    return {};
  }
}

function writeViews(views: Record<string, StashedView>): void {
  const dates = Object.keys(views).sort();
  for (const d of dates.slice(0, Math.max(0, dates.length - KEEP_DAYS))) delete views[d];
  localStorage.setItem(VIEWS_KEY, JSON.stringify(views));
}

function weekElapsed(): boolean {
  const last = Number(localStorage.getItem(LAST_KEY) ?? 0);
  return !(last > 0 && Date.now() - last < WEEK_MS);
}

/** The favorite spot closest to the user's current location - the only spot
    worth grading. Null when there are no favorites; falls back to the sole
    favorite or plain membership when there's no GPS fix to rank by. */
async function closestFavorite(): Promise<string | null> {
  const favs = getFavorites();
  if (favs.length === 0) return null;
  if (favs.length === 1) return favs[0]!;
  const pos = await getPosition();
  if (!pos) return null;
  try {
    const { spots } = await fetchIndex();
    let best: string | null = null;
    let bestKm = Infinity;
    for (const id of favs) {
      const s = spots[id];
      if (!s) continue;
      const km = distanceKm(pos, { lat: s.lat, lon: s.lon });
      if (km < bestKm) {
        bestKm = km;
        best = id;
      }
    }
    return best;
  } catch {
    return null;
  }
}

/** Called when a spot forecast is viewed: remember today's promise, but only
    when this spot is the favorite closest to where the user actually is, and
    only for a GOOD-or-better day - anything less is not worth an ask. Spots
    outside the region the user is actually in are never stashed: reading
    Tamarindo from Israel is browsing, not a session, and tomorrow's ask must
    not claim otherwise. */
export function stashView(data: SpotPayload): void {
  if (!feedbackPref() || !weekElapsed()) return;
  const home = getHome();
  const region = data.spot.region?.trim() ?? "";
  if (home?.region && region && home.region !== region) return;
  const today = todayIn(data.spot.timezone);
  const hours = data.hours.filter((h) => h.t.startsWith(today));
  if (hours.length === 0) return;
  const best = hours.reduce((a, b) => (b.rating > a.rating ? b : a));
  if (best.bucket !== "GOOD" && best.bucket !== "FIRING") return;
  void closestFavorite().then((fav) => {
    if (fav !== data.spot.id) return;
    const views = readViews();
    views[today] = {
      spot: data.spot.id,
      name: splitName(data.spot.name).name,
      at: best.t,
      predicted: { rating: best.rating, bucket: best.bucket, h: best.h, phrase: best.phrase },
    };
    writeViews(views);
  });
}

export interface FbPrompt {
  date: string;
  view: StashedView;
}

/** Yesterday's unanswered stash, if any - the one slim row Today may show.
    At most one a week: resolving (answer or dismiss) starts the clock. */
export function pendingPrompt(): FbPrompt | null {
  if (!feedbackPref() || API === "" || !weekElapsed()) return null;
  const y = new Date(Date.now() - 86_400_000);
  const yesterday = new Intl.DateTimeFormat("en-CA").format(y);
  const view = readViews()[yesterday];
  return view && !view.done ? { date: yesterday, view } : null;
}

/** Answer (or dismiss with verdict null) - either way the prompt never returns. */
export async function resolvePrompt(p: FbPrompt, verdict: "up" | "down" | null): Promise<void> {
  const views = readViews();
  const v = views[p.date];
  if (v) {
    v.done = true;
    writeViews(views);
  }
  localStorage.setItem(LAST_KEY, String(Date.now()));
  if (verdict === null) return;
  await fetch(`${API}/push/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      spot: p.view.spot,
      at: p.view.at,
      verdict,
      predicted: p.view.predicted,
      source: "web",
    }),
  }).catch(() => undefined); // best effort - never block the UI on it
}
