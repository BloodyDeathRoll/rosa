/** Which video a cam plays right now.

    A 24/7 YouTube stream gets a new video id every time it restarts - some channels
    several times a day - so the id committed in data/spots rots within hours. Each cam
    also carries its channel (`ch`) and its stream's title. The channel's public feed
    (relayed by deploy/user-api `GET /yt-feed`, cached 5 min) lists every broadcast,
    newest first, and the newest one with the same title is the same camera's current
    stream - the rule tools/cam-scan already applies ("same title - same camera, new
    broadcast id"). A channel's OTHER stream is a different beach, so nothing short of a
    title match is taken. A 0-view entry is a scheduled stream that has not started
    (measured 2026-09-15: miura's newest same-title entry was one, while the committed
    stream was live), so it is skipped. No feed, no match, or two angles of one spot
    sharing a title (which one is which?) plays the committed id, as every cam did before. */

import type { CamEntry } from "./types";

const API = (import.meta.env.VITE_USER_API as string | undefined) ?? "";
const TIMEOUT_MS = 4000;
const FEED_TTL_MS = 5 * 60_000; // the relay's cache window

interface FeedEntry {
  id: string;
  title: string;
  views: number | null;
}

// tools/cam-scan/scan.py normalize_title, ported: live badges come and go and say nothing
// about which beach the camera watches. Separators include 　 CJK space, en/em dash
// and the katakana middle dot, which Japanese broadcasters type in titles.
const NOISE = /(【\s*live\s*】|\[\s*live\s*\]|\(\s*live\s*\)|🔴|●|24\s*h(?:ours)?|live\s*(?:stream|now))/giu;
const SEPARATORS = /[\s　_.,:;|/\\~\-–—・]+/gu;

export function normalizeTitle(title: string): string {
  return title.toLowerCase().replace(NOISE, " ").replace(SEPARATORS, " ").trim();
}

const feeds = new Map<string, { at: number; entries: Promise<FeedEntry[]> }>();

function feed(ch: string): Promise<FeedEntry[]> {
  const now = Date.now();
  const cached = feeds.get(ch);
  if (cached && now - cached.at < FEED_TTL_MS) return cached.entries;
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  const entries = fetch(`${API}/yt-feed?ch=${encodeURIComponent(ch)}`, { signal: ctl.signal })
    .then((r) => (r.ok ? (r.json() as Promise<{ entries?: FeedEntry[] }>) : { entries: [] }))
    .then((b) => b.entries ?? [])
    .catch(() => {
      feeds.delete(ch); // offline or slow - the next open asks again
      return [];
    })
    .finally(() => clearTimeout(timer));
  feeds.set(ch, { at: now, entries });
  return entries;
}

/** The id each cam should play, given its channel's feed entries (newest first). */
export function pickIds(cams: CamEntry[], feedOf: (ch: string) => FeedEntry[]): string[] {
  const titles = cams.map((c) => (c.title ? normalizeTitle(c.title) : ""));
  return cams.map((c, i) => {
    const want = titles[i]!;
    if (!c.ch || !want || titles.indexOf(want) !== titles.lastIndexOf(want)) return c.yt;
    return feedOf(c.ch).find((e) => e.views !== 0 && normalizeTitle(e.title) === want)?.id ?? c.yt;
  });
}

/** The current video id of each of a spot's cams, in order. Never rejects. */
export async function currentIds(cams: CamEntry[]): Promise<string[]> {
  const chs = API ? [...new Set(cams.flatMap((c) => (c.ch ? [c.ch] : [])))] : [];
  const got = new Map(await Promise.all(chs.map(async (ch) => [ch, await feed(ch)] as const)));
  return pickIds(cams, (ch) => got.get(ch) ?? []);
}
