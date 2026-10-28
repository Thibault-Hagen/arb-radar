/* Arb Radar dashboard. Reads data/latest.json written by the scan workflow and
   re-runs the arb math (engine.js) for your stake and the venues you can use. */
(function () {
  "use strict";

  const E = window.ArbEngine;
  const $ = (id) => document.getElementById(id);
  const SCALE = 112;           // the bar spans 0-112 cents; the line sits at 100
  const REFRESH_MS = 120000;   // look for a newer scan every 2 minutes

  const store = {
    get(key, fallback) {
      try {
        const value = window.localStorage.getItem(key);
        return value === null ? fallback : JSON.parse(value);
      } catch (err) {
        return fallback;
      }
    },
    set(key, value) {
      try {
        window.localStorage.setItem(key, JSON.stringify(value));
      } catch (err) {
        /* storage unavailable (private mode); settings last for this visit only */
      }
    },
  };

  const prefs = {
    stake: store.get("arb.stake", null),
    venues: store.get("arb.venues", {}) || {},
    pair: store.get("arb.pair", "any"),
    league: store.get("arb.league", "all"),
  };

  let latest = null;
  let history = null;
  let loadedAt = 0;

  /* ---------- small helpers ---------- */

  function el(tag, props, ...kids) {
    const node = document.createElement(tag);
    if (props) {
      for (const [key, value] of Object.entries(props)) {
        if (value === null || value === undefined || value === false) continue;
        if (key === "class") node.className = value;
        else if (key === "text") node.textContent = value;
        else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
        else node.setAttribute(key, value === true ? "" : value);
      }
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid === null || kid === undefined || kid === false || kid === "") continue;
      node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return node;
  }

  const money = (x) => {
    const text = "$" + Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return x < 0 ? "(" + text + ")" : text;
  };
  const pct = (m) => (m >= 0 ? "+" + (m * 100).toFixed(2) + "%" : "(" + (Math.abs(m) * 100).toFixed(2) + "%)");
  const cents = (c) => (Math.abs(c - Math.round(c)) < 0.05 ? String(Math.round(c)) : c.toFixed(1)) + "¢";
  const american = (a) => (a > 0 ? "+" + a : "−" + Math.abs(a));
  const whenFmt = new Intl.DateTimeFormat(undefined, {
    weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
  const when = (iso) => (iso ? whenFmt.format(new Date(iso)) : "Time to be announced");
  const minutesSince = (iso, now) => Math.max(0, Math.round((now - Date.parse(iso)) / 60000));
  const ago = (mins) => {
    if (mins < 1) return "just now";
    if (mins < 60) return mins + " min ago";
    if (mins < 48 * 60) return Math.round(mins / 60) + " h ago";
    return Math.round(mins / 1440) + " days ago";
  };
  const duration = (mins) => (mins < 60 ? Math.max(1, Math.round(mins)) + " min" : (mins / 60).toFixed(1) + " h");
  const groupClass = (q) => (q.kind === "exchange" ? "pm" : "book");

  function stake() {
    const value = Number(prefs.stake);
    return value > 0 ? value : (latest && latest.settings && latest.settings.stake) || 100;
  }

  function enabledVenues() {
    const set = new Set();
    for (const [key, info] of Object.entries(latest.venues || {})) {
      const choice = prefs.venues[key];
      if (choice === undefined ? info.alert !== false : choice) set.add(key);
    }
    return set;
  }

  /* ---------- the 100-cent bar ---------- */

  function bar(legs, small) {
    const costs = E.centsPerDollar(legs);
    const total = costs[0] + costs[1];
    const width = (c) => ((Math.max(0, c) / SCALE) * 100).toFixed(3) + "%";
    const label = legs.map((q, i) => cents(costs[i]) + " on " + q.venue_title).join(" plus ") +
      " is " + cents(total) + " per dollar back" +
      (total < 100 ? ", leaving " + cents(100 - total) + " of profit." : ", " + cents(total - 100) + " over the dollar.");
    const node = el("div", { class: "bar" + (small ? " small" : ""), role: "img", "aria-label": label });
    let used = 0;
    legs.forEach((q, i) => {
      const part = Math.min(costs[i], SCALE - used);
      used += part;
      node.append(el("span", { class: "seg " + groupClass(q), style: "width:" + width(part) }));
    });
    if (total < 100) {
      node.append(el("span", { class: "gap", style: "width:" + width(100 - total) }));
    } else if (total > 100) {
      node.append(el("span", {
        class: "over",
        style: "left:" + width(100) + ";width:" + width(Math.min(total, SCALE) - 100),
      }));
    }
    node.append(el("span", { class: "line100" }));
    return node;
  }

  /* ---------- arb entries ---------- */

  function venueLink(q) {
    const safe = typeof q.url === "string" && /^https?:\/\//i.test(q.url);
    return safe ? el("a", { href: q.url, target: "_blank", rel: "noopener" }, q.venue_title) : q.venue_title;
  }

  function legInstructions(q, row) {
    if (q.kind === "exchange") {
      return [
        "Buy " + row.contracts.toLocaleString("en-US") + " “" + q.label + "” at " + cents(q.price * 100) + " on ",
        venueLink(q),
        row.fee ? ", fee " + money(row.fee) : "",
      ];
    }
    return ["Bet " + money(row.bet) + " on " + q.label + " at ", venueLink(q)];
  }

  function warningsFor(entry, now) {
    const out = [];
    const { game, legs, plan } = entry;
    if (game.league === "NFL") {
      out.push("NFL games can tie. Sportsbooks refund 2-way bets on a tie, but a YES contract loses, so check both venues' tie rules.");
    }
    legs.forEach((q, i) => {
      const row = plan.legs[i];
      if (q.note) out.push(q.venue_title + ": " + q.note + ".");
      if (q.indicative) out.push("This " + q.venue_title + " price hasn't been confirmed from its order book. Check it on " + q.venue_title + " first.");
      if (q.kind === "exchange" && q.size != null && row.contracts > q.size) {
        out.push("Only " + Math.floor(q.size).toLocaleString("en-US") + " contracts are offered at this " + q.venue_title + " price.");
      }
      if (q.updated_at) {
        const age = minutesSince(q.updated_at, now);
        if (age > 20) out.push(q.venue_title + "'s price is from " + ago(age) + ".");
      }
    });
    if (game.start) {
      const mins = (Date.parse(game.start) - now) / 60000;
      if (mins > 0 && mins < 15) out.push("Starts in " + Math.round(mins) + " min, so prices may already have moved.");
    }
    if (plan.profit <= 0) out.push("At this stake, rounding to whole contracts uses up the profit. Try a larger stake.");
    return out;
  }

  function allPrices(game, chosen, enabled, now) {
    const perSide = E.usableQuotes(game, { now });
    const tables = [0, 1].map((side) =>
      el("table", { class: "prices" },
        el("caption", { text: game.teams[side].name }),
        el("tbody", null, perSide[side].map((q) =>
          el("tr", { class: chosen.includes(q) ? "best" : null },
            el("td", null, q.venue_title, enabled.has(q.venue) ? "" : " (off)"),
            el("td", { text: q.kind === "exchange" ? q.label + " at " + cents(q.price * 100) : q.label }),
            el("td", { class: "num", text: cents(100 / q.decimal) }),
            el("td", { class: "num", text: q.updated_at ? ago(minutesSince(q.updated_at, now)) : "" })
          )
        ))
      )
    );
    return el("details", { class: "all-prices" },
      el("summary", { text: "Every price for this game" }),
      el("p", { class: "hint", text: "Cost to get $1 back, fees included. The bold rows are the pair above." }),
      tables);
  }

  function renderEntry(entry, enabled, now) {
    const { game, legs, plan, margin } = entry;
    const costs = E.centsPerDollar(legs);
    const total = costs[0] + costs[1];
    const legRows = legs.map((q, i) =>
      el("tr", null,
        el("th", { scope: "row" },
          el("b", { text: game.teams[i].name }),
          el("span", { class: "how" },
            el("span", { class: "dot", style: "background:var(--" + groupClass(q) + ")" }),
            legInstructions(q, plan.legs[i]))),
        el("td", { text: money(plan.legs[i].cost) })
      )
    );
    const ledger = el("table", { class: "ledger" },
      el("tbody", null,
        legRows,
        el("tr", { class: "sum first-sum" }, el("th", { scope: "row", text: "You spend" }), el("td", { text: money(plan.stake) })),
        el("tr", { class: "sum" }, el("th", { scope: "row", text: "You get back, whoever wins" }), el("td", { text: money(plan.payout) })),
        el("tr", { class: "sum profit" }, el("th", { scope: "row", text: "Locked-in profit" }), el("td", null, el("span", { text: money(plan.profit) })))
      )
    );
    const warnings = warningsFor(entry, now);
    return el("article", { class: "entry" },
      el("div", { class: "entry-top" },
        el("div", null,
          el("p", { class: "meta" },
            el("span", { class: "tag", text: game.league }),
            el("time", { datetime: game.start || game.date, text: when(game.start) })),
          el("h3", { text: game.title })),
        el("p", { class: "margin", text: pct(margin) })),
      bar(legs, false),
      el("p", { class: "bar-caption",
        text: "Both sides together cost " + cents(total) + " for every $1 you get back, so " + cents(100 - total) + " of each dollar is yours." }),
      ledger,
      warnings.length ? el("ul", { class: "warnings" }, warnings.map((w) => el("li", { text: w }))) : null,
      allPrices(game, legs, enabled, now)
    );
  }

  function renderArbs(arbs, enabled, now) {
    const box = $("arbs");
    box.replaceChildren();
    if (!arbs.length) {
      const off = Object.keys(latest.venues || {}).length - enabled.size;
      box.append(el("div", { class: "empty" },
        el("strong", { text: "No locked-in profit right now." }),
        el("p", { text: "That's the usual state: the two sides of a game normally cost more than $1 together. The games closest to a lock are below, and this page checks for a new scan every couple of minutes." }),
        off > 0 ? el("p", { text: off + (off === 1 ? " venue is" : " venues are") + " turned off in your venue settings." }) : null));
      return;
    }
    for (const entry of arbs) box.append(renderEntry(entry, enabled, now));
  }

  /* ---------- near misses ---------- */

  function offer(q, game, side) {
    if (q.kind === "exchange") return q.label + " at " + cents(q.price * 100) + " on " + q.venue_title;
    const odds = q.american != null ? american(q.american) : q.decimal.toFixed(2);
    return (game.teams[side].short || game.teams[side].name) + " " + odds + " on " + q.venue_title;
  }

  function renderMisses(misses) {
    const list = $("misses");
    list.replaceChildren();
    if (!misses.length) {
      list.append(el("li", null, el("p", { class: "row-detail", text: "No games have prices from two different venues yet." })));
      return;
    }
    for (const m of misses) {
      const costs = E.centsPerDollar(m.legs);
      const total = costs[0] + costs[1];
      list.append(el("li", null,
        el("div", { class: "row-head" },
          el("span", { class: "tag", text: m.game.league }),
          el("span", { class: "title", text: m.game.title }),
          el("span", { class: "pct " + (m.margin >= 0 ? "gain" : "loss"), text: pct(m.margin) })),
        bar(m.legs, true),
        el("p", { class: "row-detail",
          text: offer(m.legs[0], m.game, 0) + " and " + offer(m.legs[1], m.game, 1) + " cost " + cents(total) +
            " per $1 back. " + when(m.game.start) + "." })
      ));
    }
  }

  /* ---------- history and sources ---------- */

  function renderHistory() {
    const box = $("history");
    box.replaceChildren();
    const items = (history && history.items) || [];
    if (!items.length) {
      box.append(el("p", { class: "lede", text: "None yet. Every arb the scanner finds is logged here with how long it lasted." }));
      return;
    }
    const list = el("ol", { class: "history" });
    for (const item of items.slice(0, 40)) {
      const lasted = Math.max(0, (Date.parse(item.last_seen) - Date.parse(item.first_seen)) / 60000);
      const seen = item.scans > 1
        ? "seen for about " + duration(lasted) + " across " + item.scans + " scans"
        : "seen in one scan";
      list.append(el("li", null,
        el("span", { class: "when", text: when(item.first_seen) }),
        el("span", { class: "what", text: item.title }),
        el("span", { class: "peak", text: pct(item.peak_margin || 0) }),
        el("span", { class: "how", text: (item.venues || []).join(" + ") + ", " + seen })));
    }
    box.append(list);
  }

  function renderSources() {
    const box = $("sources");
    box.replaceChildren();
    for (const s of latest.sources || []) {
      let summary;
      if (!s.enabled) summary = "Turned off in config.toml.";
      else if (s.id === "espn") summary = s.games + " games on the schedule";
      else if (s.id === "odds_api" && latest.odds_api && !latest.odds_api.has_key) summary = "Not connected yet";
      else summary = s.games + " games, " + s.matched + " lined up with the schedule";
      const dd = el("dd", null, summary);
      if (s.id === "odds_api" && latest.odds_api && latest.odds_api.has_key) {
        const b = latest.odds_api.budget || {};
        dd.append(el("span", { class: "muted",
          text: b.remaining + " free credits left this month, " + b.used_today + " of " + b.allowance_today + " used today" }));
      }
      if (s.note) dd.append(el("span", { class: "muted", text: s.note }));
      for (const err of s.errors || []) dd.append(el("span", { class: "err", text: err }));
      box.append(el("div", null, el("dt", { text: s.title }), dd));
    }
  }

  /* ---------- controls ---------- */

  function renderVenueChips(enabled) {
    const box = $("venues");
    box.replaceChildren();
    const entries = Object.entries(latest.venues || {}).sort((a, b) => a[1].title.localeCompare(b[1].title));
    const groups = [["pm", "Prediction markets"], ["book", "Sportsbooks"]];
    for (const [group, title] of groups) {
      const items = entries.filter(([, info]) => info.group === group);
      if (!items.length) continue;
      box.append(el("div", { class: "venue-group" },
        el("p", { text: title }),
        el("div", { class: "chips" }, items.map(([key, info]) =>
          el("button", {
            type: "button", class: "chip", "aria-pressed": enabled.has(key) ? "true" : "false",
            onclick: () => {
              prefs.venues[key] = !enabled.has(key);
              store.set("arb.venues", prefs.venues);
              render();
            },
          }, el("span", { class: "swatch", style: "background:var(--" + group + ")" }), info.title)
        ))
      ));
    }
    const total = entries.length;
    $("venues-summary").textContent = "Venues you can use (" + enabled.size + " of " + total + " on)";
  }

  function renderLeagueOptions() {
    const select = $("league");
    const leagues = [...new Set((latest.games || []).map((g) => g.league))].sort();
    const current = prefs.league;
    select.replaceChildren(el("option", { value: "all", text: "All leagues" }),
      leagues.map((code) => el("option", { value: code, text: code })));
    select.value = leagues.includes(current) ? current : "all";
  }

  function wireControls() {
    const stakeInput = $("stake");
    stakeInput.addEventListener("input", () => {
      const value = Number(stakeInput.value);
      if (value > 0) {
        prefs.stake = value;
        store.set("arb.stake", value);
        if (latest) render();
      }
    });
    $("pair").addEventListener("change", (event) => {
      prefs.pair = event.target.value;
      store.set("arb.pair", prefs.pair);
      if (latest) render();
    });
    $("league").addEventListener("change", (event) => {
      prefs.league = event.target.value;
      store.set("arb.league", prefs.league);
      if (latest) render();
    });
  }

  /* ---------- page ---------- */

  function renderUpdated(now) {
    const node = $("updated");
    const mins = minutesSince(latest.generated_at, now);
    const stale = mins > 45;
    node.textContent = "Scanned " + ago(mins) +
      (stale ? ". Scans normally run every 15 minutes; the repository's Actions tab shows why this one is late." : "");
    node.classList.toggle("stale", stale);
  }

  function render() {
    const now = Date.now();
    const enabled = enabledVenues();
    $("stake").value = String(stake());
    $("pair").value = prefs.pair;
    renderLeagueOptions();
    renderVenueChips(enabled);
    renderUpdated(now);
    const result = E.analyze(latest.games || [], {
      now,
      venues: enabled,
      pair: prefs.pair,
      league: $("league").value,
      stake: stake(),
      minMargin: (latest.settings && latest.settings.min_margin) || 0,
      includeLive: latest.settings && latest.settings.include_live,
      nearMissCount: 15,
    });
    renderArbs(result.arbs, enabled, now);
    renderMisses(result.misses);
    renderHistory();
    renderSources();
  }

  function showWaiting() {
    $("updated").textContent = "No scan results yet";
    $("arbs").replaceChildren(el("div", { class: "empty" },
      el("strong", { text: "Waiting for the first scan." }),
      el("p", { text: "Open the repository's Actions tab, choose Scan, and select Run workflow. This page fills in about a minute after it finishes." })));
  }

  async function load() {
    const bust = "?t=" + Date.now();
    try {
      const response = await fetch("data/latest.json" + bust, { cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      latest = await response.json();
      loadedAt = Date.now();
    } catch (err) {
      if (!latest) showWaiting();
      return;
    }
    try {
      const response = await fetch("data/history.json" + bust, { cache: "no-store" });
      history = response.ok ? await response.json() : history;
    } catch (err) {
      /* history is optional */
    }
    render();
  }

  wireControls();
  load();
  setInterval(() => {
    if (document.visibilityState === "visible") load();
  }, REFRESH_MS);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && Date.now() - loadedAt > 60000) load();
  });
})();
