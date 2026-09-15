// A YouTube channel's public Atom feed, relayed with CORS for the cam player
// (web/src/cams.ts). A 24/7 stream mints a new video id every time it restarts - some
// channels several times a day - so an id pinned in data/spots rots within hours. The
// channel feed lists every broadcast, with its title, needs no API key and spends no
// quota; browsers just cannot read it (no CORS header). The app matches the cam's
// committed title against these entries.

export interface FeedEntry {
  id: string;
  title: string;
  published: string;
  /** null when the feed carries no count. 0 = a scheduled stream that has not started -
      measured 2026-09-15: all three 0-view same-title entries were upcoming, and every
      live or ended one had views. */
  views: number | null;
}

export const CHANNEL_ID = /^UC[\w-]{22}$/;
export const FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id=";
export const FEED_TTL_S = 300;

const ENTITIES: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" };

function unescapeXml(s: string): string {
  return s.replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos);/gi, (_, e: string) => {
    if (e[0] !== "#") return ENTITIES[e.toLowerCase()]!;
    const hex = e[1] === "x" || e[1] === "X";
    return String.fromCodePoint(parseInt(e.slice(hex ? 2 : 1), hex ? 16 : 10));
  });
}

/** A channel feed's entries, newest first. An entry it cannot read is skipped, never thrown. */
export function parseFeed(xml: string): FeedEntry[] {
  const out: FeedEntry[] = [];
  for (const [, body] of xml.matchAll(/<entry>([\s\S]*?)<\/entry>/g)) {
    const id = /<yt:videoId>([\w-]{11})<\/yt:videoId>/.exec(body!)?.[1];
    const title = /<title>([\s\S]*?)<\/title>/.exec(body!)?.[1];
    const published = /<published>([^<]+)<\/published>/.exec(body!)?.[1] ?? "";
    const views = /<media:statistics views="(\d+)"/.exec(body!)?.[1];
    if (id && title !== undefined)
      out.push({ id, title: unescapeXml(title), published, views: views === undefined ? null : Number(views) });
  }
  return out.sort((a, b) => Date.parse(b.published || "0") - Date.parse(a.published || "0"));
}
