#!/usr/bin/env python3
"""social_aggregator — every 4h. Pulls hot/trending content from Reddit (public
JSON), Hacker News (Firebase API), and Google Trends (pytrends, optional), computes
a velocity score per item, derives trending-topic terms, and snapshots both into
Supabase (content_items + trending_snapshots). Twitter/X public trends are folded
in best-effort and degrade to nothing when unavailable.

Manual entry point:
  python social_aggregator.py            # default subreddits + HN + trends
"""
from __future__ import annotations

import asyncio
import logging
import sys

import config
import social_sources as src
import supa

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("social.agg")


async def run_aggregation(subreddits=None) -> dict:
    snapshot_at = supa.now_iso()

    content = await src.collect_trending(subreddits=subreddits)
    # Best-effort X/Twitter trends (degrade gracefully).
    try:
        content.extend(await src.twitter_trends())
    except Exception as e:  # noqa: BLE001
        log.info(f"twitter trends skipped: {e}")

    # Stamp the snapshot time onto every content row.
    for r in content:
        r["snapshot_at"] = snapshot_at

    written_c = await supa.upsert_content(content)
    log.info(f"content_items: upserted {written_c}")

    # Derive trending topics from the content velocity.
    topics = src.topic_keywords(content, top_n=40)
    trend_rows = []
    for rank, t in enumerate(topics):
        trend_rows.append({
            "topic": t["topic"], "platform": "all", "velocity": t["velocity"],
            "rank": rank + 1, "snapshot_at": snapshot_at,
        })
    # Per-platform trending too (so platform filters return data).
    by_platform: dict = {}
    for r in content:
        by_platform.setdefault(r.get("platform") or "other", []).append(r)
    for platform, rows in by_platform.items():
        for rank, t in enumerate(src.topic_keywords(rows, top_n=15)):
            trend_rows.append({
                "topic": t["topic"], "platform": platform, "velocity": t["velocity"],
                "rank": rank + 1, "snapshot_at": snapshot_at,
            })

    written_t = await supa.upsert_trending(trend_rows)
    log.info(f"trending_snapshots: upserted {written_t}")

    out = {"content_items": len(content), "content_written": written_c,
           "trending_topics": len(trend_rows), "topics_written": written_t,
           "google_trends": src.google_trends_available(), "snapshot_at": snapshot_at}
    log.info(f"done: {out}")
    return out


async def main() -> None:
    args = [a for a in sys.argv[1:] if a.strip()]
    subs = args or None
    print(await run_aggregation(subs))


if __name__ == "__main__":
    asyncio.run(main())
