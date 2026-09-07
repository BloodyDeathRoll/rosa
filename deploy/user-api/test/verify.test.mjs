// The user API's security boundary: Google ID-token verification and Rosa's own
// session tokens. No dependencies - `node --test` (Node >= 22.18, type-stripping
// lets it import the .ts sources directly).
import assert from "node:assert/strict";
import { test } from "node:test";
import { resetJwksCache, TokenError, verifyIdToken } from "../src/google.ts";
import { mint, secretsEqual, verify } from "../src/session.ts";

const CLIENT_ID = "test-client.apps.googleusercontent.com";
const NOW = Date.UTC(2026, 8, 7, 12, 0, 0);
const enc = new TextEncoder();

const b64url = (bytes) =>
  Buffer.from(bytes).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

async function rsaPair(kid) {
  const pair = await crypto.subtle.generateKey(
    { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
    true,
    ["sign", "verify"],
  );
  const jwk = await crypto.subtle.exportKey("jwk", pair.publicKey);
  return { priv: pair.privateKey, jwk: { ...jwk, kid, alg: "RS256", use: "sig" } };
}

async function sign(priv, header, claims) {
  const h = b64url(enc.encode(JSON.stringify(header)));
  const p = b64url(enc.encode(JSON.stringify(claims)));
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", priv, enc.encode(`${h}.${p}`));
  return `${h}.${p}.${b64url(sig)}`;
}

const goodClaims = (over = {}) => ({
  iss: "https://accounts.google.com",
  aud: CLIENT_ID,
  sub: "1234567890",
  email: "surfer@example.com",
  email_verified: true,
  name: "Surfer",
  picture: "https://lh3.googleusercontent.com/x",
  iat: Math.floor(NOW / 1000) - 60,
  exp: Math.floor(NOW / 1000) + 3600,
  ...over,
});

test("a valid Google credential yields the profile claims", async () => {
  resetJwksCache();
  const { priv, jwk } = await rsaPair("k1");
  const token = await sign(priv, { alg: "RS256", kid: "k1", typ: "JWT" }, goodClaims());
  const claims = await verifyIdToken(token, CLIENT_ID, { now: NOW, fetchJwks: async () => [jwk] });
  assert.deepEqual(claims, {
    sub: "1234567890",
    email: "surfer@example.com",
    name: "Surfer",
    picture: "https://lh3.googleusercontent.com/x",
  });
});

test("expired, wrong audience, wrong issuer, unverified email and unknown kid are all refused", async () => {
  const { priv, jwk } = await rsaPair("k1");
  const cases = [
    ["exp", goodClaims({ exp: Math.floor(NOW / 1000) - 1 }), "k1"],
    ["aud", goodClaims({ aud: "someone-else" }), "k1"],
    ["iss", goodClaims({ iss: "https://evil.example" }), "k1"],
    ["email_verified", goodClaims({ email_verified: false }), "k1"],
    ["kid", goodClaims(), "k-unknown"],
  ];
  for (const [why, claims, kid] of cases) {
    resetJwksCache();
    const token = await sign(priv, { alg: "RS256", kid }, claims);
    await assert.rejects(
      verifyIdToken(token, CLIENT_ID, { now: NOW, fetchJwks: async () => [jwk] }),
      (e) => e instanceof TokenError && e.message === why,
      why,
    );
  }
});

test("a token signed by a different key, or tampered, fails the signature check", async () => {
  resetJwksCache();
  const { jwk } = await rsaPair("k1");
  const other = await rsaPair("k1"); // same kid, different key
  const forged = await sign(other.priv, { alg: "RS256", kid: "k1" }, goodClaims());
  await assert.rejects(
    verifyIdToken(forged, CLIENT_ID, { now: NOW, fetchJwks: async () => [jwk] }),
    (e) => e instanceof TokenError && e.message === "signature",
  );
  const { priv } = await rsaPair("k2");
  const good = await sign(priv, { alg: "RS256", kid: "k2" }, goodClaims());
  const [h, p, s] = good.split(".");
  const tamperedClaims = b64url(enc.encode(JSON.stringify(goodClaims({ sub: "999" }))));
  resetJwksCache();
  await assert.rejects(
    verifyIdToken(`${h}.${tamperedClaims}.${s}`, CLIENT_ID, {
      now: NOW,
      fetchJwks: async () => [(await rsaPair("k2")).jwk],
    }),
    (e) => e instanceof TokenError,
  );
  for (const junk of ["", "abc", "a.b", "a.b.c", `${h}.${p}.!!`]) {
    await assert.rejects(verifyIdToken(junk, CLIENT_ID, { now: NOW, fetchJwks: async () => [] }), TokenError);
  }
});

test("alg=none and HS256 headers are refused before any key lookup", async () => {
  let fetched = 0;
  for (const header of [{ alg: "none", kid: "k1" }, { alg: "HS256", kid: "k1" }, { alg: "RS256" }]) {
    const h = b64url(enc.encode(JSON.stringify(header)));
    const p = b64url(enc.encode(JSON.stringify(goodClaims())));
    await assert.rejects(
      verifyIdToken(`${h}.${p}.AAAA`, CLIENT_ID, {
        now: NOW,
        fetchJwks: async () => {
          fetched++;
          return [];
        },
      }),
      (e) => e instanceof TokenError && e.message === "alg",
    );
  }
  assert.equal(fetched, 0);
});

test("session tokens round-trip, expire, and fail on tamper or wrong secret", async () => {
  const secret = "s3cret-" + "x".repeat(40);
  const token = await mint({ sub: "42", exp: NOW + 1000, ep: 3 }, secret);
  assert.match(token, /^v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/);
  assert.deepEqual(await verify(token, secret, NOW), { sub: "42", exp: NOW + 1000, ep: 3 });
  assert.equal(await verify(token, secret, NOW + 1000), null, "expired");
  assert.equal(await verify(token, "other-secret", NOW), null, "wrong secret");
  const [v, payload, sig] = token.split(".");
  const forgedPayload = b64url(enc.encode(JSON.stringify({ sub: "43", exp: NOW + 1000, ep: 3 })));
  assert.equal(await verify(`${v}.${forgedPayload}.${sig}`, secret, NOW), null, "tampered payload");
  assert.equal(await verify(`${v}.${payload}.${sig.slice(0, -2)}AA`, secret, NOW), null, "tampered sig");
  for (const junk of ["", "v1", "v1.a", "v2.a.b", "v1.a.b", "v1..", "v1.%%%.###"]) {
    assert.equal(await verify(junk, secret, NOW), null, JSON.stringify(junk));
  }
});

test("secretsEqual compares without throwing on length mismatch", async () => {
  assert.equal(await secretsEqual("abc", "abc"), true);
  assert.equal(await secretsEqual("abc", "abd"), false);
  assert.equal(await secretsEqual("abc", "abcd"), false);
  assert.equal(await secretsEqual("", "x"), false);
});
