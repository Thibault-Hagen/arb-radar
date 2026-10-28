"""Push alerts: ntfy (free phone notifications, no account) and/or a Discord webhook."""

from __future__ import annotations

from .timeutil import local_label


def _money(value: float) -> str:
    return f"${value:,.2f}"


def format_alert(opp, tz_name: str) -> tuple[str, str]:
    game = opp.game
    title = f"Arb +{opp.margin * 100:.2f}%: {game.title}"
    lines = [f"{game.league} · {local_label(game.start, tz_name)}"]
    for side, (quote, row) in enumerate(zip(opp.quotes, opp.plan["legs"])):
        team = game.teams[side].name
        if quote.kind == "exchange":
            lines.append(f"{team} via {quote.venue_title}: {quote.label} @ {quote.price * 100:.0f}¢ → "
                         f"{row['contracts']} contracts ({_money(row['cost'])} incl. {_money(row['fee'])} fee)")
        else:
            lines.append(f"{team} via {quote.venue_title}: {quote.label} → bet {_money(row['bet'])}")
    plan = opp.plan
    lines.append(f"Spend {_money(plan['stake'])} → get back {_money(plan['payout'])} either way "
                 f"(+{_money(plan['profit'])})")
    for warning in opp.warnings[:2]:
        lines.append(f"⚠ {warning}")
    lines.append("Prices move fast: confirm both sides before placing either.")
    return title, "\n".join(lines)


def send_alerts(fetcher, opportunities, secrets, tz_name: str) -> list[str]:
    """Returns a short log line per alert attempt. Never raises."""
    log = []
    if not opportunities or not (secrets.ntfy_topic or secrets.discord_webhook):
        return log
    for opp in opportunities[:5]:
        title, message = format_alert(opp, tz_name)
        if secrets.ntfy_topic:
            try:
                payload = {"topic": secrets.ntfy_topic, "title": title, "message": message,
                           "tags": ["moneybag"], "priority": 4}
                if secrets.site_url:
                    payload["click"] = secrets.site_url
                fetcher.post_json(secrets.ntfy_server.rstrip("/") + "/", payload)
                log.append(f"ntfy: sent '{title}'")
            except Exception as exc:  # keep scanning even if alerts fail
                log.append(f"ntfy: failed ({exc})")
        if secrets.discord_webhook:
            try:
                content = f"**{title}**\n{message}"
                if secrets.site_url:
                    content += f"\n{secrets.site_url}"
                fetcher.post_json(secrets.discord_webhook, {"content": content[:1900]})
                log.append(f"discord: sent '{title}'")
            except Exception as exc:
                log.append(f"discord: failed ({exc})")
    return log
