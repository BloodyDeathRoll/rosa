// The push-api write routes behind a per-IP limit (OPEN-ITEMS 33a). A fake binding
// stands in for Workers Rate Limiting and a fake fetch for rosa-push.
import assert from "node:assert/strict";
import { test } from "node:test";
import { MAX_RELAY_BYTES, relay } from "../src/relay.ts";

function fakeLimit(max) {
  const seen = new Map();
  return {
    async limit({ key }) {
      seen.set(key, (seen.get(key) ?? 0) + 1);
      return { success: seen.get(key) <= max };
    },
  };
}

function fakeUpstream() {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  return { calls, fetchImpl };
}

const req = (method, path, body, ip = "1.1.1.1") =>
  new Request(`https://x${path}`, {
    method,
    headers: { "Content-Type": "application/json", "cf-connecting-ip": ip },
    body,
  });

test("a relay route forwards the body with the secret, and returns rosa-push's answer", async () => {
  const { calls, fetchImpl } = fakeUpstream();
  const env = { PUSH_RELAY_SECRET: "s3cret", PUSH_API_ORIGIN: "https://push.example" };
  const res = await relay(req("POST", "/push/contact", '{"message":"hi"}'), env, "/push/contact", fetchImpl);
  assert.equal(res.status, 200);
  assert.deepEqual(await res.json(), { ok: true });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://push.example/api/contact");
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.headers["x-relay-secret"], "s3cret");
  assert.equal(calls[0].init.body, '{"message":"hi"}');
});

test("sub takes POST and DELETE; contact refuses DELETE", async () => {
  const { calls, fetchImpl } = fakeUpstream();
  const env = { PUSH_RELAY_SECRET: "s" };
  assert.equal((await relay(req("DELETE", "/push/sub", "{}"), env, "/push/sub", fetchImpl)).status, 200);
  assert.equal(calls[0].url, "https://rosa-push.vercel.app/api/sub");
  assert.equal(calls[0].init.method, "DELETE");
  assert.equal((await relay(req("DELETE", "/push/contact", "{}"), env, "/push/contact", fetchImpl)).status, 405);
  assert.equal(calls.length, 1);
});

test("each IP gets its own budget; over it is a 429 and nothing is forwarded", async () => {
  const { calls, fetchImpl } = fakeUpstream();
  const env = { PUSH_RELAY_SECRET: "s", CONTACT_LIMIT: fakeLimit(2) };
  const send = (ip) => relay(req("POST", "/push/contact", "{}", ip), env, "/push/contact", fetchImpl);
  assert.equal((await send("1.1.1.1")).status, 200);
  assert.equal((await send("1.1.1.1")).status, 200);
  const third = await send("1.1.1.1");
  assert.equal(third.status, 429);
  assert.deepEqual(await third.json(), { error: "rate" });
  assert.equal((await send("2.2.2.2")).status, 200);
  assert.equal(calls.length, 3);
});

test("the routes do not share a budget", async () => {
  const { fetchImpl } = fakeUpstream();
  const env = { PUSH_RELAY_SECRET: "s", CONTACT_LIMIT: fakeLimit(1), SUB_LIMIT: fakeLimit(1) };
  assert.equal((await relay(req("POST", "/push/contact", "{}"), env, "/push/contact", fetchImpl)).status, 200);
  assert.equal((await relay(req("POST", "/push/sub", "{}"), env, "/push/sub", fetchImpl)).status, 200);
});

test("without the shared secret the relay refuses rather than forwarding unsigned", async () => {
  const { calls, fetchImpl } = fakeUpstream();
  assert.equal((await relay(req("POST", "/push/feedback", "{}"), {}, "/push/feedback", fetchImpl)).status, 503);
  assert.equal(calls.length, 0);
});

test("an oversized body is refused; an unreachable rosa-push is a 502", async () => {
  const { fetchImpl } = fakeUpstream();
  const env = { PUSH_RELAY_SECRET: "s" };
  const big = "x".repeat(MAX_RELAY_BYTES + 1);
  assert.equal((await relay(req("POST", "/push/contact", big), env, "/push/contact", fetchImpl)).status, 413);
  const down = async () => {
    throw new TypeError("network");
  };
  assert.equal((await relay(req("POST", "/push/contact", "{}"), env, "/push/contact", down)).status, 502);
});

test("other paths are not the relay's", async () => {
  assert.equal(await relay(req("POST", "/auth/google", "{}"), {}, "/auth/google"), null);
});
