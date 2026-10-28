// Checks that the dashboard's JavaScript math agrees with the Python scanner.
// Usage: node tests/engine.test.js path/to/data/latest.json
"use strict";

const assert = require("assert");
const fs = require("fs");
const E = require("../web/engine.js");

const file = process.argv[2] || "site/data/latest.json";
const data = JSON.parse(fs.readFileSync(file, "utf8"));
const now = Date.parse(data.generated_at);
let checks = 0;

// Fee examples from Kalshi's and Polymarket's published schedules.
assert.strictEqual(E.orderFee(0.07, 0.01, 100, 0.55), 1.74);
assert.strictEqual(E.orderFee(0.07, 0.01, 1, 0.5), 0.02);
assert.strictEqual(E.orderFee(0.05, 0.01, 100, 0.5), 1.25);
assert.strictEqual(E.round2(44.885), 44.89);
checks += 4;

const result = E.analyze(data.games, {
  now,
  stake: data.settings.stake,
  minMargin: data.settings.min_margin,
  includeLive: data.settings.include_live,
  nearMissCount: 50,
});

assert.strictEqual(result.arbs.length, data.opportunities.length, "same number of arbs");
for (const expected of data.opportunities) {
  const got = result.arbs.find((a) => a.game.key === expected.game);
  assert.ok(got, "arb found for " + expected.title);
  assert.ok(Math.abs(got.margin - expected.margin) < 1e-4, "margin for " + expected.title);
  assert.deepStrictEqual(got.legs.map((q) => q.venue), expected.legs.map((l) => l.venue));
  assert.strictEqual(got.plan.stake, expected.plan.stake, "stake for " + expected.title);
  assert.strictEqual(got.plan.payout, expected.plan.payout, "payout for " + expected.title);
  assert.strictEqual(got.plan.profit, expected.plan.profit, "profit for " + expected.title);
  checks += 6;
}

for (const expected of data.near_misses) {
  const got = result.misses.find((m) => m.game.key === expected.game);
  assert.ok(got, "near miss found for " + expected.title);
  assert.ok(Math.abs(got.margin - expected.margin) < 1e-4, "near-miss margin for " + expected.title);
  checks += 2;
}

// Turning a venue off must change the answer, never break it.
const withoutBooks = E.analyze(data.games, {
  now, stake: 100, venues: new Set(["kalshi", "polymarket_us"]), nearMissCount: 50,
});
for (const entry of withoutBooks.arbs.concat(withoutBooks.misses)) {
  assert.ok(entry.legs.every((q) => q.kind === "exchange"), "only prediction-market legs");
  checks += 1;
}

console.log("engine.test.js: " + checks + " checks passed");
