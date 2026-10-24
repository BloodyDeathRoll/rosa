// /ig — the one link in the Instagram bio. Instagram lets a profile carry a single link and
// the Graph API cannot change it, so the bio points here forever and this function sends the
// visitor on to whatever the newest reel is about, with that reel's UTM campaign. Tachyon's
// publisher updates the target in Edge Config (`tachyon-links`, key `rosa_ig`) right after each
// publish, so attribution per reel works without anyone editing the profile.
//
// Edge runtime, no dependencies: reads the Edge Config connection string from EDGE_CONFIG
// (https://edge-config.vercel.com/<id>?token=<token>) and fetches one item. Any failure falls
// back to the plain bio campaign so the link never dead-ends. Only rosa.surf targets are
// honoured; the function is not an open redirect.

const FALLBACK = "https://rosa.surf/?utm_source=instagram&utm_medium=social&utm_campaign=bio";
const KEY = "rosa_ig";

export default async function handler() {
  let target = FALLBACK;
  try {
    const conn = process.env.EDGE_CONFIG;
    if (conn) {
      const u = new URL(conn);
      const r = await fetch(`${u.origin}${u.pathname}/item/${KEY}?token=${u.searchParams.get("token")}`, {
        headers: { "cache-control": "no-cache" },
      });
      if (r.ok) {
        const v = await r.json();
        if (typeof v === "string" && /^https:\/\/rosa\.surf\//.test(v)) target = v;
      }
    }
  } catch {
    // fall through to FALLBACK
  }
  return new Response(null, {
    status: 302,
    headers: { Location: target, "Cache-Control": "no-store", "X-Robots-Tag": "noindex" },
  });
}
