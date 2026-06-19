"""Daily curated brief — social-intel.

Runs once a day at BRIEF_HOUR_UTC (05:00 UTC) as an in-process background task
(same shape as the aggregation loop). It queries the last 24h of trending-topic +
content snapshots, ranks by velocity, packages the most significant items, attests
the package through MINT for verifiable provenance, and upserts it into the
`daily_briefs` table. The paid `daily_brief` tool just reads that row back.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import config
import mint_integration
import social_sources as src
import supa

logger = logging.getLogger("social.curator")

SERVER = config.SERVER_SLUG
PRICE = config.PRICE_DAILY_BRIEF


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _expires_at(date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return (d + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")


def related_briefs(exclude: str) -> list:
    return [{"server": s, "price": p, "tool": "daily_brief"}
            for s, p in config.NETWORK_BRIEFS.items() if s != exclude]


async def _curate_signals(since_utc: int) -> tuple[dict, int]:
    """Build the social brief body from the last 24h of snapshots. Returns
    (signals, count)."""
    # Top trending topics across all platforms (latest snapshot).
    trend = await supa.latest_trending(platform="all", limit=25)
    top_trending_topics = [{"topic": r.get("topic"), "velocity": r.get("velocity"),
                            "rank": r.get("rank")} for r in trend]

    # Fastest-moving content in the last 24h.
    viral = await supa.viral_content(since_utc=since_utc, limit=15)
    viral_content = [{"platform": r.get("platform"), "title": r.get("title"),
                      "url": r.get("url"), "community": r.get("community"),
                      "score": r.get("score"), "comments": r.get("comments"),
                      "velocity": r.get("velocity"), "sentiment": r.get("sentiment")}
                     for r in viral]

    # Sentiment shifts: average sentiment of the most-active content, by platform.
    recent = await supa.viral_content(since_utc=since_utc, limit=200)
    by_platform: dict = {}
    for r in recent:
        s = r.get("sentiment")
        if s is None:
            continue
        by_platform.setdefault(r.get("platform") or "other", []).append(float(s))
    sentiment_shifts = []
    for plat, scores in by_platform.items():
        avg = round(sum(scores) / len(scores), 4) if scores else 0.0
        sentiment_shifts.append({"platform": plat, "sentiment_score": avg,
                                 "label": src.sentiment_label(avg), "sample_size": len(scores)})

    # Most-active communities by total engagement.
    community_totals: dict = {}
    for r in recent:
        comm = r.get("community") or "other"
        community_totals[comm] = community_totals.get(comm, 0) + \
            (r.get("score") or 0) + (r.get("comments") or 0)
    most_active_communities = [{"community": c, "engagement": e}
                               for c, e in sorted(community_totals.items(),
                                                  key=lambda kv: kv[1], reverse=True)[:10]]

    signals = {
        "top_trending_topics": top_trending_topics,
        "viral_content": viral_content,
        "sentiment_shifts": sentiment_shifts,
        "most_active_communities": most_active_communities,
    }
    count = (len(top_trending_topics) + len(viral_content)
             + len(sentiment_shifts) + len(most_active_communities))
    return signals, count


async def run_curation(date_str: str | None = None) -> dict:
    """Generate, attest, and store today's brief. Idempotent per date (upsert)."""
    date_str = date_str or _today()
    import time
    since_utc = int(time.time() - 24 * 3600)
    signals, count = await _curate_signals(since_utc)

    brief = {
        "brief_date": date_str, "server": SERVER, "signal_count": count,
        "signals": signals, "expires_at": _expires_at(date_str),
        "related_briefs": related_briefs(SERVER),
    }
    # Attest for provenance (sync httpx → run off the event loop; fail-open).
    attestation = await asyncio.to_thread(
        mint_integration.attest_data, brief, "analysis",
        f"Daily {SERVER} brief: {count} signals")
    brief["provenance"] = attestation

    row = {
        "brief_date": date_str, "brief_data": brief, "signal_count": count,
        "attestation_hash": attestation.get("attestation_hash"),
        "expires_at": _expires_at(date_str),
    }
    res = await supa.upsert("daily_briefs", [row], "brief_date")
    if isinstance(res, dict) and res.get("error"):
        logger.warning(f"daily brief upsert failed: {str(res)[:200]}")
    else:
        logger.info(f"daily brief stored: {date_str} ({count} signals, "
                    f"attested={attestation.get('mint_verified')})")
    return brief


async def get_brief(date_str: str | None = None) -> dict | None:
    """Read a stored brief; None if missing or expired."""
    date_str = date_str or _today()
    rows = await supa.select("daily_briefs",
                             {"select": "*", "brief_date": f"eq.{date_str}", "limit": "1"})
    if not rows:
        return None
    row = rows[0]
    exp = row.get("expires_at")
    if exp:
        try:
            if datetime.now(timezone.utc) >= datetime.fromisoformat(exp.replace("Z", "+00:00")):
                return None
        except Exception:  # noqa: BLE001
            pass
    return row.get("brief_data")


async def bump_purchase(date_str: str) -> None:
    """Best-effort purchase counter via RPC (no-op if the function is absent)."""
    try:
        await supa.rpc("increment_brief_purchase", {"p_brief_date": date_str})
    except Exception:  # noqa: BLE001
        pass


async def curator_loop() -> None:
    """Sleep until BRIEF_HOUR_UTC each day, then curate. Cancellable."""
    while True:
        now = datetime.now(timezone.utc)
        secs = now.hour * 3600 + now.minute * 60 + now.second
        wait = (config.BRIEF_HOUR_UTC * 3600 - secs) % 86400 or 86400
        try:
            await asyncio.sleep(wait)
            if supa.configured():
                await run_curation()
        except asyncio.CancelledError:
            break
        except Exception as e:  # noqa: BLE001
            logger.warning(f"curator loop error: {e}")
            await asyncio.sleep(3600)
