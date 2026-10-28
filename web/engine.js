/* Arb math for the dashboard. Mirrors arb/engine.py so the page can re-run it
   when you change your stake or which venues you can use. Works in browsers
   (window.ArbEngine) and in Node (module.exports) for tests. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ArbEngine = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const PAIR = { "pm|book": "pm-book", "book|pm": "pm-book", "pm|pm": "pm-pm", "book|book": "book-book" };

  const round2 = (x) => Math.floor(x * 100 + 0.5 + 1e-9) / 100;
  const ceilTo = (x, step) => (step > 0 ? Math.ceil(Number((x / step).toFixed(9))) * step : x);
  const groupOf = (q) => (q.kind === "exchange" ? "pm" : "book");

  function orderFee(rate, roundTo, contracts, price) {
    if (!rate || contracts <= 0) return 0;
    return Number(ceilTo(rate * contracts * price * (1 - price), roundTo || 0).toFixed(6));
  }

  function marginOf(decimals) {
    const total = decimals.reduce((sum, d) => sum + 1 / d, 0);
    return 1 / total - 1;
  }

  /* Quotes per side, filtered to enabled venues and fresh enough, best first. */
  function usableQuotes(game, opts) {
    const now = opts.now || Date.now();
    const out = { 0: [], 1: [] };
    for (const q of game.quotes || []) {
      if (opts.venues && !opts.venues.has(q.venue)) continue;
      if (opts.maxAgeMinutes && q.updated_at) {
        const age = (now - Date.parse(q.updated_at)) / 60000;
        if (age > opts.maxAgeMinutes) continue;
      }
      out[q.side].push(q);
    }
    out[0].sort((a, b) => b.decimal - a.decimal);
    out[1].sort((a, b) => b.decimal - a.decimal);
    return out;
  }

  /* Best pair across two venues; a same-venue pair only if it is itself an arb. */
  function bestCombo(perSide, pair) {
    let cross = null;
    let same = null;
    for (const q0 of perSide[0]) {
      for (const q1 of perSide[1]) {
        const kind = PAIR[groupOf(q0) + "|" + groupOf(q1)];
        if (pair && pair !== "any" && kind !== pair) continue;
        const option = { margin: marginOf([q0.decimal, q1.decimal]), legs: [q0, q1], pair: kind };
        if (q0.venue === q1.venue) {
          if (!same || option.margin > same.margin) same = option;
        } else if (!cross || option.margin > cross.margin) {
          cross = option;
        }
      }
    }
    if (same && same.margin > 0 && (!cross || same.margin > cross.margin)) return same;
    return cross;
  }

  /* Whole contracts, fees rounded up to the cent, sportsbook bets to the cent. */
  function stakePlan(legs, stake) {
    const totalInverse = legs.reduce((sum, q) => sum + 1 / q.decimal, 0);
    const target = stake / totalInverse;
    const hasExchange = legs.some((q) => q.kind === "exchange");
    const payout = hasExchange ? Math.floor(target) : round2(target);
    const rows = legs.map((q) => {
      if (q.kind === "exchange") {
        const contracts = payout;
        const fee = orderFee(q.fee_rate, q.fee_round, contracts, q.price);
        return { contracts, fee: round2(fee), cost: round2(contracts * q.price + fee), payout: contracts };
      }
      const bet = round2(payout / q.decimal);
      return { bet, cost: bet, payout: round2(bet * q.decimal) };
    });
    const spent = round2(rows.reduce((sum, r) => sum + r.cost, 0));
    const worst = rows.length ? Math.min(...rows.map((r) => r.payout)) : 0;
    const profit = round2(worst - spent);
    return { stake: spent, payout: round2(worst), profit, roi: spent ? profit / spent : 0, legs: rows };
  }

  /* Cost of one $1 payout on each leg, in cents, fees included (for the 100-cent bar). */
  function centsPerDollar(legs) {
    return legs.map((q) => 100 / q.decimal);
  }

  function analyze(games, opts) {
    const arbs = [];
    const misses = [];
    const now = opts.now || Date.now();
    for (const game of games) {
      if (opts.league && opts.league !== "all" && game.league !== opts.league) continue;
      if (!opts.includeLive && game.start && Date.parse(game.start) <= now) continue;
      const combo = bestCombo(usableQuotes(game, opts), opts.pair);
      if (!combo) continue;
      const entry = Object.assign({ game, plan: stakePlan(combo.legs, opts.stake) }, combo);
      if (entry.margin > 0 && entry.margin >= (opts.minMargin || 0)) arbs.push(entry);
      else misses.push(entry);
    }
    arbs.sort((a, b) => b.margin - a.margin);
    misses.sort((a, b) => b.margin - a.margin);
    return { arbs, misses: misses.slice(0, opts.nearMissCount || 15) };
  }

  return { round2, orderFee, marginOf, usableQuotes, bestCombo, stakePlan, centsPerDollar, analyze };
});
