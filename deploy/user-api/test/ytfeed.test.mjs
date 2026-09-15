// The cam feed relay's parser (src/ytfeed.ts). `node --test`, no dependencies.
import assert from "node:assert/strict";
import { test } from "node:test";
import { CHANNEL_ID, parseFeed } from "../src/ytfeed.ts";

const entry = (id, title, published, views = 100) =>
  `<entry><id>yt:video:${id}</id><yt:videoId>${id}</yt:videoId><title>${title}</title>` +
  `<published>${published}</published><media:group><media:title>${title}</media:title>` +
  (views === null ? "" : `<media:community><media:statistics views="${views}"/></media:community>`) +
  `</media:group></entry>`;
const feed = (...entries) =>
  `<?xml version="1.0" encoding="UTF-8"?><feed><title>malpaisurfcam</title>${entries.join("")}</feed>`;

test("entries come back newest first, whatever order the feed used", () => {
  const got = parseFeed(
    feed(
      entry("oyA-DINr7O0", "Santa Teresa Live Surf Cam", "2026-09-15T02:14:53+00:00"),
      entry("9aJXhLz8g6k", "Santa Teresa Live Surf Cam", "2026-09-15T11:00:42+00:00"),
      entry("F9yvDBMdM38", "Santa Teresa Live Surf Cam", "2026-09-14T01:31:32+00:00"),
    ),
  );
  assert.deepEqual(
    got.map((e) => e.id),
    ["9aJXhLz8g6k", "oyA-DINr7O0", "F9yvDBMdM38"],
  );
});

test("the channel's own title is not an entry", () => {
  const got = parseFeed(feed(entry("9aJXhLz8g6k", "Santa Teresa Live Surf Cam", "2026-09-15T11:00:42+00:00")));
  assert.equal(got.length, 1);
  assert.equal(got[0].title, "Santa Teresa Live Surf Cam");
});

test("XML entities in a title are decoded", () => {
  const got = parseFeed(
    feed(entry("wi18kVOwmsc", "חוף הגולשים ראשל&quot;צ &amp; Beach &#39;Cam&#x27;", "2026-09-14T00:00:00+00:00")),
  );
  assert.equal(got[0].title, `חוף הגולשים ראשל"צ & Beach 'Cam'`);
});

test("the view count is read - 0 marks a stream that has not started - and a missing one is null", () => {
  const got = parseFeed(
    feed(
      entry("_UzlXZz9fho", "Miura Beach", "2026-09-15T10:00:00+00:00", 0),
      entry("49NubJ78KWU", "Miura Beach", "2026-09-01T10:00:00+00:00", 125387),
      entry("aA53Iq3jbcI", "Miura Beach", "2026-08-01T10:00:00+00:00", null),
    ),
  );
  assert.deepEqual(
    got.map((e) => e.views),
    [0, 125387, null],
  );
});

test("an entry without a video id is skipped", () => {
  const got = parseFeed(
    feed(
      "<entry><title>no id</title><published>2026-09-15T00:00:00+00:00</published></entry>",
      entry("9aJXhLz8g6k", "Santa Teresa Live Surf Cam", "2026-09-15T11:00:42+00:00"),
    ),
  );
  assert.deepEqual(
    got.map((e) => e.id),
    ["9aJXhLz8g6k"],
  );
});

test("an empty or broken feed is no entries, not an error", () => {
  assert.deepEqual(parseFeed(""), []);
  assert.deepEqual(parseFeed("<html>consent page</html>"), []);
});

test("only UC channel ids are relayed", () => {
  assert.ok(CHANNEL_ID.test("UCjDgFtxT4FlTO1CeYweHj_A"));
  assert.ok(!CHANNEL_ID.test("@malpaisurfcam1"));
  assert.ok(!CHANNEL_ID.test("UCjDgFtxT4FlTO1CeYweHj_A&x=1"));
  assert.ok(!CHANNEL_ID.test(""));
});
