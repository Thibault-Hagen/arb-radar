"""One scan: fetch every source, line up games, find arbs, write the dashboard data."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from . import __version__
from .budget import OddsBudget
from .config import Secrets, Settings
from .engine import find_opportunities, is_upcoming, margin_of, usable_quotes
from .fees import FeeModel
from .history import mark_alerted, pick_alerts, update_history
from .http import HttpError
from .leagues import LEAGUES
from .matching import MATCHED, GameBook
from .notify import send_alerts
from .sources import BOOK_TITLES, espn, kalshi, odds_api, polymarket_us
from .timeutil import et_date, iso, parse_iso

EXCHANGE_TITLES = {"kalshi": "Kalshi", "polymarket_us": "Polymarket US"}
MAX_BBO_REFRESHES = 30


@dataclass
class SourceStatus:
    id: str
    title: str
    enabled: bool = True
    games: int = 0
    matched: int = 0
    quotes: int = 0
    errors: list = field(default_factory=list)
    note: str = ""
    unmatched: list = field(default_factory=list)

    def count(self, game, verdict, sg) -> None:
        if game is None:
            return
        self.games += 1
        self.quotes += len(sg.quotes)
        if verdict == MATCHED:
            self.matched += 1
        elif self.id != "espn" and len(self.unmatched) < 40:
            # Games this feed has that no earlier feed had; useful for spotting name mismatches.
            self.unmatched.append({"league": sg.league, "date": sg.date.isoformat() if sg.date else None,
                                   "sides": [[*s.names[:2], s.code] for s in sg.sides],
                                   "ref": {k: v for k, v in sg.ref.items() if k != "rules"}})

    def fail(self, message: str) -> None:
        if len(self.errors) < 8:
            self.errors.append(message[:300])

    def to_dict(self) -> dict:
        ok = self.enabled and (not self.errors or self.games > 0)
        return {"id": self.id, "title": self.title, "enabled": self.enabled, "ok": ok,
                "games": self.games, "matched": self.matched, "quotes": self.quotes,
                "errors": self.errors, "note": self.note}


def _read(folder: Path | None, name: str, default):
    if folder is None:
        return default
    path = Path(folder) / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(folder: Path, name: str, data) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _sample(debug: dict, key: str, value) -> None:
    """Keep one small raw sample per feed so parsing can be checked against real data."""
    if key in debug or not value or (isinstance(value, dict) and value.get("events") == []):
        return
    text = json.dumps(value, default=str)
    debug[key] = value if len(text) < 40_000 else {"truncated": text[:40_000]}


def _refresh_polymarket(fetcher, games, now, status: SourceStatus, debug: dict) -> int:
    """Re-price Polymarket US markets that could plausibly be part of an arb."""
    wanted: set[str] = set()
    for game in games:
        per_side = usable_quotes(game, now)
        for side in (0, 1):
            others = [q for q in per_side[1 - side] if q.venue != "polymarket_us"] or per_side[1 - side]
            if not others:
                continue
            for quote in game.quotes[side]:
                if quote.source != "polymarket_us" or not quote.ref.get("market_slug"):
                    continue
                if quote.indicative or margin_of([quote.decimal, others[0].decimal]) > -0.02:
                    wanted.add(quote.ref["market_slug"])
    by_slug: dict[str, list] = {}
    for game in games:
        for side in (0, 1):
            for quote in game.quotes[side]:
                slug = quote.ref.get("market_slug")
                if quote.source == "polymarket_us" and slug in wanted:
                    by_slug.setdefault(slug, []).append(quote)
    refreshed, dropped = 0, set()
    for slug in sorted(by_slug)[:MAX_BBO_REFRESHES]:
        try:
            bbo = polymarket_us.fetch_bbo(fetcher, slug)
        except Exception as exc:
            status.fail(f"best bid/offer for {slug}: {exc}")
            continue
        _sample(debug, "polymarket_us_bbo", bbo)
        kept = {id(q) for q in polymarket_us.apply_bbo(by_slug[slug], bbo, now)}
        dropped |= {id(q) for q in by_slug[slug] if id(q) not in kept}
        refreshed += 1
    if dropped:
        for game in games:
            for side in (0, 1):
                game.quotes[side] = [q for q in game.quotes[side] if id(q) not in dropped]
    if refreshed:
        status.note = (status.note + "; " if status.note else "") + f"re-priced {refreshed} order books"
    return refreshed


def run_scan(settings: Settings, fetcher, prev_dir, out_dir, now: datetime, secrets: Secrets,
             send: bool = True, log=print) -> dict:
    prev_dir = Path(prev_dir) if prev_dir else None
    out_data = Path(out_dir) / "data"
    state = _read(prev_dir, "state.json", {})
    history = _read(prev_dir, "history.json", {"items": []})
    leagues = [LEAGUES[code] for code in settings.leagues]
    today = et_date(now)
    last_date = today + timedelta(days=settings.days_ahead)
    days = [today + timedelta(days=n) for n in range(settings.days_ahead + 1)]
    book, statuses, debug = GameBook(), [], {}

    def admit(sg) -> bool:
        """Only games in the scan window; feeds also list games weeks ahead."""
        day = sg.date or et_date(sg.start)
        return day is not None and today <= day <= last_date

    # 1. ESPN: schedules and DraftKings lines (free).
    st = SourceStatus("espn", "DraftKings lines via ESPN", settings.sources.get("espn", True))
    if st.enabled:
        for lg in leagues:
            for day in days:
                try:
                    data = espn.fetch_scoreboard(fetcher, lg, day)
                except Exception as exc:
                    st.fail(f"{lg.code} {day}: {exc}")
                    continue
                _sample(debug, "espn", {"events": (data.get("events") or [])[:1]})
                for sg in espn.parse_scoreboard(data, lg.code, now):
                    if admit(sg):
                        st.count(*book.add(sg), sg)
    statuses.append(st)

    # 2. Kalshi (free, public market data).
    st = SourceStatus("kalshi", "Kalshi", settings.sources.get("kalshi", True))
    if st.enabled:
        for lg in leagues:
            try:
                series = kalshi.fetch_series(fetcher, lg.kalshi_series)
            except Exception as exc:
                series = {}
                st.fail(f"{lg.kalshi_series} series info: {exc}")
            try:
                events = kalshi.fetch_events(fetcher, lg.kalshi_series)
            except Exception as exc:
                st.fail(f"{lg.code} games: {exc}")
                continue
            _sample(debug, "kalshi", {"series": series, "events": events[:1]})
            parsed = kalshi.parse_events(events, lg.code, series, settings.kalshi_taker_rate,
                                         settings.fee_round, now, lg.ties)
            for sg in parsed:
                if admit(sg):
                    st.count(*book.add(sg), sg)
    statuses.append(st)

    # 3. Polymarket US (free, public gateway).
    st = SourceStatus("polymarket_us", "Polymarket US", settings.sources.get("polymarket_us", True))
    if st.enabled:
        try:
            pm_leagues = polymarket_us.fetch_leagues(fetcher)
        except Exception as exc:
            pm_leagues = None
            st.fail(f"league list: {exc}")
        if pm_leagues is not None:
            _sample(debug, "polymarket_us_leagues",
                    [{k: lg.get(k) for k in ("name", "slug", "abbreviation")}
                     for lg in pm_leagues if isinstance(lg, dict)][:400])
            missing = []
            for lg in leagues:
                slug = polymarket_us.pick_league_slug(pm_leagues, lg)
                events, errors = None, []
                # If the league list didn't name it, try the usual slugs directly.
                for candidate in ([slug] if slug else list(lg.pmus_slugs)):
                    try:
                        found = polymarket_us.fetch_league_events(fetcher, candidate)
                    except Exception as exc:
                        errors.append(f"{lg.code} games ({candidate}): {exc}")
                        continue
                    if found or slug:
                        events = found
                        break
                if events is None:
                    if slug:
                        for message in errors:
                            st.fail(message)
                    else:
                        missing.append(lg.code)
                    continue
                _sample(debug, "polymarket_us_events", events[:1])
                for sg in polymarket_us.parse_events(events, lg.code, settings.polymarket_us_taker_rate,
                                                     settings.fee_round, now):
                    if admit(sg):
                        st.count(*book.add(sg), sg)
            if missing:
                st.note = "no league found for " + ", ".join(missing)
    pm_status = st
    statuses.append(st)

    # 4. The Odds API (500 free credits a month, spent by the budget).
    st = SourceStatus("odds_api", "The Odds API (more sportsbooks)", settings.sources.get("odds_api", True))
    oa = settings.odds_api
    budget = OddsBudget(state.setdefault("odds_api", {}), oa.monthly_credits, oa.reset_day,
                        oa.max_credits_per_day, oa.min_minutes_between_calls,
                        odds_api.credit_cost(oa.bookmakers))
    cache = state.setdefault("odds_cache", {})
    decisions: dict[str, str] = {}
    if st.enabled and not secrets.odds_api_key:
        st.note = "Add the ODDS_API_KEY secret to compare FanDuel, BetMGM, Caesars and more."
    elif st.enabled:
        upcoming_by_league = {}
        for game in book.games:
            if game.start and game.start > now:
                current = upcoming_by_league.get(game.league)
                upcoming_by_league[game.league] = min(current, game.start) if current else game.start
        order = sorted(leagues, key=lambda lg: upcoming_by_league.get(lg.code) or now + timedelta(days=99))
        for lg in order:
            go, reason = budget.decide(lg.odds_api_key, now, upcoming_by_league.get(lg.code),
                                       oa.lookahead_hours)
            decisions[lg.code] = reason
            if not go:
                continue
            # If the API ever rejects the optional extras (deep links, relayed exchanges),
            # fall back to plain sportsbook odds and remember that for next time.
            plain_books = [b for b in oa.bookmakers if b not in odds_api.EXCHANGES]
            attempts = [(plain_books, False)]
            if not state.get("odds_api_plain"):
                attempts.insert(0, (oa.bookmakers, True))
            try:
                for n, (books, links) in enumerate(attempts):
                    try:
                        events, headers = odds_api.fetch_odds(fetcher, secrets.odds_api_key, lg.odds_api_key,
                                                              books, now, oa.lookahead_hours,
                                                              settings.include_live, links)
                        if n > 0:
                            state["odds_api_plain"] = True
                        break
                    except HttpError as exc:
                        if exc.status == 422 and n + 1 < len(attempts):
                            continue
                        raise
            except HttpError as exc:
                if exc.status in (401, 403):
                    st.fail("The Odds API rejected the key (check the ODDS_API_KEY secret).")
                    break
                if exc.status == 429:
                    st.fail("The Odds API quota is used up for now.")
                    break
                st.fail(f"{lg.code}: {exc}")
                continue
            except Exception as exc:
                st.fail(f"{lg.code}: {exc}")
                continue
            budget.record(lg.odds_api_key, now, headers)
            decisions[lg.code] = "refreshed now"
            cache[lg.code] = {"fetched_at": iso(now), "events": events}
            _sample(debug, "odds_api", events[:1])
        exchange_fees = {
            "kalshi": FeeModel(settings.kalshi_taker_rate, settings.fee_round),
            "polymarket_us": FeeModel(settings.polymarket_us_taker_rate, settings.fee_round),
        }
        max_age = timedelta(minutes=settings.max_quote_age_minutes)
        for lg in leagues:
            entry = cache.get(lg.code) or {}
            fetched = parse_iso(entry.get("fetched_at"))
            if fetched is None or now - fetched > max_age:
                cache.pop(lg.code, None)
                continue
            live = [e for e in entry.get("events") or []
                    if (parse_iso(e.get("commence_time")) or now) > now - timedelta(hours=1)]
            entry["events"] = live
            for sg in odds_api.parse_odds(live, lg.code, exchange_fees, fetched):
                if admit(sg):
                    st.count(*book.add(sg), sg)
    for code in list(cache):
        if code not in settings.leagues:
            del cache[code]
    statuses.append(st)

    # 5. Keep upcoming games, refresh promising Polymarket US prices, find arbs.
    games = [g for g in book.games if is_upcoming(g, now, settings.include_live, last_date)]
    if pm_status.enabled:
        _refresh_polymarket(fetcher, games, now, pm_status, debug)

    max_age = timedelta(minutes=settings.max_quote_age_minutes)
    arbs, misses = find_opportunities(games, now, settings.stake, settings.min_margin,
                                      settings.near_miss_count, max_age=max_age)

    al = settings.alerts
    alert_venues = set(al.venues) if al.venues else None
    alert_pool, _ = find_opportunities(
        [g for g in games if g.start is None or g.start > now + timedelta(minutes=5)],
        now, settings.stake, max(al.min_margin, 0.0), 0, venues=alert_venues,
        max_age=timedelta(minutes=al.max_quote_age_minutes), allow_indicative=False)

    history = update_history(history, arbs, now)
    alerts = pick_alerts(alert_pool, state, now, al.min_margin, al.realert_hours)
    alert_log = []
    if alerts and send:
        alert_log = send_alerts(fetcher, alerts, secrets, settings.timezone)
        if any("sent" in line for line in alert_log):
            mark_alerted(state, alerts, now)

    # 6. Write the dashboard data.
    venues: dict[str, dict] = {}
    game_rows = []
    for game in sorted(games, key=lambda g: (g.start or datetime.max.replace(tzinfo=now.tzinfo), g.league)):
        per_side = usable_quotes(game, now, max_age=max_age)
        if not per_side[0] or not per_side[1]:
            continue
        venue_set = {q.venue for side in (0, 1) for q in per_side[side]}
        if len(venue_set) < 2:
            continue
        quotes = [q.to_dict(side) for side in (0, 1) for q in per_side[side]]
        for side in (0, 1):
            for q in per_side[side]:
                venues.setdefault(q.venue, {
                    "title": q.venue_title, "kind": q.kind,
                    "group": "pm" if q.kind == "exchange" else "book",
                    "alert": q.venue in (alert_venues or {q.venue}),
                })
        game_rows.append({
            "key": game.key, "league": game.league, "title": game.title, "date": game.date.isoformat(),
            "start": iso(game.start), "status": game.status, "home_index": game.home_index,
            "teams": [{"key": t.key, "name": t.name, "short": t.short} for t in game.teams],
            "quotes": quotes, "sources": sorted(game.sources), "notes": game.notes,
            "rules": game.refs.get("kalshi_rules") or "",
        })

    payload = {
        "version": __version__,
        "generated_at": iso(now),
        "settings": {
            "stake": settings.stake, "min_margin": settings.min_margin, "days_ahead": settings.days_ahead,
            "include_live": settings.include_live, "timezone": settings.timezone,
            "alert_venues": sorted(alert_venues) if alert_venues else [],
            "alert_min_margin": al.min_margin,
        },
        "sources": [s.to_dict() for s in statuses],
        "odds_api": {
            "has_key": bool(secrets.odds_api_key), "budget": budget.summary(now),
            "decisions": decisions, "cached": {k: v.get("fetched_at") for k, v in cache.items()},
            "bookmakers": [BOOK_TITLES.get(b, EXCHANGE_TITLES.get(b, b)) for b in oa.bookmakers],
        },
        "venues": venues,
        "counts": {"games": len(game_rows), "arbs": len(arbs), "alerts": len(alerts),
                   "http_calls": getattr(fetcher, "calls", None)},
        "games": game_rows,
        "opportunities": [o.to_dict() for o in arbs],
        "near_misses": [o.to_dict() for o in misses],
        "alert_log": alert_log,
    }
    _write(out_data, "latest.json", payload)
    _write(out_data, "history.json", history)
    _write(out_data, "state.json", state)
    _write(out_data, "debug.json", {
        "generated_at": iso(now), "samples": debug,
        "unmatched": {s.id: s.unmatched for s in statuses if s.unmatched},
    })

    summary = {
        "games": len(game_rows), "arbs": len(arbs), "alerts_sent": len(alert_log),
        "sources": {s.id: f"{s.games} games ({s.matched} matched){' ERR' if s.errors else ''}" for s in statuses},
        "odds_api": decisions, "best": f"{arbs[0].margin * 100:+.2f}% {arbs[0].game.title}" if arbs else
        (f"closest {misses[0].margin * 100:+.2f}% {misses[0].game.title}" if misses else "none"),
    }
    for s in statuses:
        for err in s.errors:
            log(f"[{s.id}] {err}")
    for line in alert_log:
        log(line)
    return summary
