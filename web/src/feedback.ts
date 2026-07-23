/** Next-open retro feedback (v0.2 calibration loop): viewing a spot's forecast
    stashes that day's promise locally; the NEXT day's first open asks one tap —
    "was the call right?" — and ships {spot, at, predicted, verdict} to the
    feedback API. Nothing is ever asked in the moment, max one prompt per day.
    Gated by the Profile "Spot feedback" toggle. */

import { splitName, todayIn } from "./format";
import type { SpotPayload } from "./types";

const API = (import.meta.env.VITE_PUSH_API as string | undefined) ?? "";
const VIEWS_KEY = "rosa.fb.views";
const PREF_KEY = "rosa.fb.pref"; // "on" (default) | "off"
const KEEP_DAYS = 7;
const MIN_RATING = 30; // don't ask about days Rosa itself called sub-FAIR

interface StashedView {
  spot: string;
  name: string;
  at: string; // best hour's spot-local ISO — the session being graded
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

/** Called when a spot forecast is viewed: remember today's promise (last
    viewed spot wins — the one most likely surfed). */
export function stashView(data: SpotPayload): void {
  if (!feedbackPref()) return;
  const today = todayIn(data.spot.timezone);
  const day = data.days.find((d) => d.date === today);
  if (!day || day.rating_max < MIN_RATING) return;
  const hours = data.hours.filter((h) => h.t.startsWith(today));
  if (hours.length === 0) return;
  const best = hours.reduce((a, b) => (b.rating > a.rating ? b : a));
  const views = readViews();
  views[today] = {
    spot: data.spot.id,
    name: splitName(data.spot.name).name,
    at: best.t,
    predicted: { rating: best.rating, bucket: best.bucket, h: best.h, phrase: best.phrase },
  };
  writeViews(views);
}

export interface FbPrompt {
  date: string;
  view: StashedView;
}

/** Yesterday's unanswered stash, if any — the one slim row Today may show. */
export function pendingPrompt(): FbPrompt | null {
  if (!feedbackPref() || API === "") return null;
  const y = new Date(Date.now() - 86_400_000);
  const yesterday = new Intl.DateTimeFormat("en-CA").format(y);
  const view = readViews()[yesterday];
  return view && !view.done ? { date: yesterday, view } : null;
}

/** Answer (or dismiss with verdict null) — either way the prompt never returns. */
export async function resolvePrompt(p: FbPrompt, verdict: "up" | "down" | null): Promise<void> {
  const views = readViews();
  const v = views[p.date];
  if (v) {
    v.done = true;
    writeViews(views);
  }
  if (verdict === null) return;
  await fetch(`${API}/api/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      spot: p.view.spot,
      at: p.view.at,
      verdict,
      predicted: p.view.predicted,
      source: "web",
    }),
  }).catch(() => undefined); // best effort — never block the UI on it
}
