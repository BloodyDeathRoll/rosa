// node --test: the x-relay-secret check on the public write routes (OPEN-ITEMS 33a).
import { test } from "node:test";
import assert from "node:assert/strict";
import { GRACE_UNTIL, relayOk } from "../api/_relay.js";

const req = (h) => ({ headers: h === undefined ? {} : { "x-relay-secret": h } });

test("with the secret set, only the relay's header passes", () => {
  process.env.PUSH_RELAY_SECRET = "relay-s3cret";
  assert.equal(relayOk(req("relay-s3cret")), true);
  assert.equal(relayOk(req("relay-s3creu")), false);
  assert.equal(relayOk(req("")), false);
  assert.equal(relayOk(req(undefined)), false);
  assert.equal(relayOk(req(["relay-s3cret"])), false); // repeated header arrives as an array
});

test("grace lets a direct write through until GRACE_UNTIL, never after", () => {
  process.env.PUSH_RELAY_SECRET = "relay-s3cret";
  assert.equal(relayOk(req(undefined), { grace: true, now: GRACE_UNTIL - 1 }), true);
  assert.equal(relayOk(req(undefined), { grace: true, now: GRACE_UNTIL }), false);
  assert.equal(relayOk(req(undefined), { grace: false, now: GRACE_UNTIL - 1 }), false);
});

test("an unset PUSH_RELAY_SECRET does not enforce", () => {
  delete process.env.PUSH_RELAY_SECRET;
  assert.equal(relayOk(req(undefined)), true);
});
