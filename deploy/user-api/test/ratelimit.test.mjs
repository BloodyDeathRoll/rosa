// POST /auth/google is capped per client IP (audit 2026-09-11). A fake binding
// stands in for Workers Rate Limiting: it counts calls per key.
import assert from "node:assert/strict";
import { test } from "node:test";
import { signInAllowed } from "../src/ratelimit.ts";

function fakeLimit(max) {
  const seen = new Map();
  return {
    keys: seen,
    async limit({ key }) {
      seen.set(key, (seen.get(key) ?? 0) + 1);
      return { success: seen.get(key) <= max };
    },
  };
}

const req = (ip) => new Request("https://x/auth/google", { method: "POST", headers: ip ? { "cf-connecting-ip": ip } : {} });

test("each IP gets its own budget; the one over it is refused", async () => {
  const SIGNIN_LIMIT = fakeLimit(2);
  assert.equal(await signInAllowed(req("1.1.1.1"), { SIGNIN_LIMIT }), true);
  assert.equal(await signInAllowed(req("1.1.1.1"), { SIGNIN_LIMIT }), true);
  assert.equal(await signInAllowed(req("1.1.1.1"), { SIGNIN_LIMIT }), false);
  assert.equal(await signInAllowed(req("2.2.2.2"), { SIGNIN_LIMIT }), true);
});

test("no client IP header shares one bucket rather than skipping the limit", async () => {
  const SIGNIN_LIMIT = fakeLimit(1);
  assert.equal(await signInAllowed(req(null), { SIGNIN_LIMIT }), true);
  assert.equal(await signInAllowed(req(null), { SIGNIN_LIMIT }), false);
  assert.deepEqual([...SIGNIN_LIMIT.keys.keys()], ["unknown"]);
});

test("without the binding, sign-in is not limited", async () => {
  assert.equal(await signInAllowed(req("1.1.1.1"), {}), true);
});
