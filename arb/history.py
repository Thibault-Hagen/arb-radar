"""Rolling log of arbs the scanner has seen, plus alert de-duplication."""

from __future__ import annotations

from datetime import datetime, timedelta

from .timeutil import iso, parse_iso


def update_history(history: dict, opportunities, now: datetime, keep_days: int = 14, cap: int = 400) -> dict:
    items = {item["id"]: item for item in (history or {}).get("items", []) if isinstance(item, dict) and item.get("id")}
    for opp in opportunities:
        item = items.get(opp.key)
        if item is None:
            item = items[opp.key] = {
                "id": opp.key, "first_seen": iso(now), "title": opp.game.title,
                "league": opp.game.league, "start": iso(opp.game.start), "pair": opp.pair,
                "venues": [q.venue_title for q in opp.quotes], "labels": [q.label for q in opp.quotes],
                "peak_margin": 0.0, "scans": 0,
            }
        item["last_seen"] = iso(now)
        item["last_margin"] = round(opp.margin, 5)
        item["peak_margin"] = round(max(item.get("peak_margin") or 0.0, opp.margin), 5)
        item["scans"] = int(item.get("scans") or 0) + 1
    cutoff = now - timedelta(days=keep_days)
    kept = [i for i in items.values() if (parse_iso(i.get("last_seen")) or now) >= cutoff]
    kept.sort(key=lambda i: i.get("last_seen") or "", reverse=True)
    return {"updated_at": iso(now), "items": kept[:cap]}


def pick_alerts(opportunities, state: dict, now: datetime, min_margin: float, realert_hours: float) -> list:
    sent = state.setdefault("alerts", {})
    chosen = []
    for opp in opportunities:
        if opp.margin < min_margin or opp.plan.get("profit", 0) <= 0:
            continue
        previous = sent.get(opp.key)
        if previous:
            last = parse_iso(previous.get("at"))
            recent = last is not None and now - last < timedelta(hours=realert_hours)
            if recent and opp.margin < float(previous.get("margin") or 0) + 0.005:
                continue
        chosen.append(opp)
    return chosen


def mark_alerted(state: dict, opportunities, now: datetime) -> None:
    sent = state.setdefault("alerts", {})
    for opp in opportunities:
        sent[opp.key] = {"at": iso(now), "margin": round(opp.margin, 5)}
    cutoff = now - timedelta(days=3)
    for key in [k for k, v in sent.items() if (parse_iso(v.get("at")) or now) < cutoff]:
        del sent[key]
