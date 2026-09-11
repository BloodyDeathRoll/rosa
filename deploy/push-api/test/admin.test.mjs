// node --test: the constant-time admin check (audit 2026-09-11).
import { test } from "node:test";
import assert from "node:assert/strict";
import { adminOk } from "../api/_admin.js";

const req = (h) => ({ headers: h === undefined ? {} : { "x-admin-secret": h } });

test("the right secret passes, anything else is refused", () => {
  process.env.PUSH_ADMIN_SECRET = "s3cret-value";
  assert.equal(adminOk(req("s3cret-value")), true);
  assert.equal(adminOk(req("s3cret-valuf")), false);
  assert.equal(adminOk(req("s3cret")), false); // shorter: no length-mismatch throw
  assert.equal(adminOk(req("")), false);
  assert.equal(adminOk(req(undefined)), false);
  assert.equal(adminOk(req(["s3cret-value"])), false); // repeated header arrives as an array
});

test("an unset PUSH_ADMIN_SECRET refuses everyone", () => {
  delete process.env.PUSH_ADMIN_SECRET;
  assert.equal(adminOk(req("")), false);
  assert.equal(adminOk(req("anything")), false);
});
