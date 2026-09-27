// Run with `npm test` (Node >= 22 strips the TypeScript types of lib/caseUrl.ts natively).
import assert from "node:assert/strict";
import test from "node:test";
import { caseFromLocation, urlWithCase } from "../lib/caseUrl.ts";

const BASE = "https://rinatrizvanov.github.io/prsguard-demo/";

test("the case is stored in the query string and survives an in-page anchor", () => {
  const url = urlWithCase(`${BASE}#trace`, "B");
  assert.equal(url, `${BASE}?case=B#trace`);
  const u = new URL(url);
  assert.equal(caseFromLocation(u.search, u.hash), "B");
});

test("?case=B#trace is read as case B (bookmark / refresh)", () => {
  assert.equal(caseFromLocation("?case=B", "#trace"), "B");
});

test("switching case keeps the anchor; clearing removes only the parameter", () => {
  assert.equal(urlWithCase(`${BASE}?case=B#trace`, "D"), `${BASE}?case=D#trace`);
  assert.equal(urlWithCase(`${BASE}?case=B#trace`, null), `${BASE}#trace`);
});

test("legacy #case=X links are still understood and rewritten to ?case=X", () => {
  assert.equal(caseFromLocation("", "#case=E"), "E");
  assert.equal(urlWithCase(`${BASE}#case=E`, "E"), `${BASE}?case=E`);
});

test("invalid values are ignored", () => {
  assert.equal(caseFromLocation("?case=b", ""), null);
  assert.equal(caseFromLocation("?case=AB", ""), null);
  assert.equal(caseFromLocation("", "#trace"), null);
});
