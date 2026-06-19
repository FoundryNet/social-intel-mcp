"""Shared logic behind the MCP tools + REST routes: 6 paid social-trends operations
+ free mint_info, with x402 gating. Each paid tool runs payment_gate.precheck at
its per-tool price first, then (additively) attaches a MINT provenance attestation.
Sentiment is a deterministic lexicon heuristic — no paid LLM.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import config
import daily_curator
import mint_integration
import payment_gate
import social_sources as src
import supa

logger = logging.getLogger("social.core")


def _billing(d):
    g = d.get("gate")
    if g == "free":
        cap, cnt = d.get("cap"), d.get("count")
        return {"tier": "free", "used_today": cnt, "daily_free": cap,
                "remaining_today": (cap - cnt) if (cap is not None and cnt is not None) else None}
    if g == "paid":
        return {"tier": "paid", "charged_usdc": d.get("amount_usdc")}
    if g == "api_key":
        return {"tier": "api_key", "note": "billed to your Forge account"}
    return {"tier": "free", "note": "gating inert"}


def _now_utc() -> float:
    import time
    return time.time()


async def _attest(result: dict, summary: str) -> dict:
    """Additive MINT provenance (sync httpx → off the event loop; fail-open)."""
    return await asyncio.to_thread(mint_integration.attest_data, result, "analysis", summary)


# ── trending_topics ($0.01) ───────────────────────────────────────────────────
async def do_trending_topics(platform, category, *, agent_key, payment_tx=None, api_key=None):
    platform = (platform or "all").strip().lower()
    params = {k: v for k, v in {"platform": platform, "category": category}.items() if v}
    price = payment_gate._price_for("trending_topics")
    dec = await payment_gate.precheck("trending_topics", params, price, agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        return dec["body"]

    rows = await supa.latest_trending(platform=platform, limit=25)
    if not rows:
        # Cold-start fallback: derive topics live from the sources.
        live = await src.collect_trending()
        rows = [{"topic": t["topic"], "platform": platform, "velocity": t["velocity"],
                 "rank": i + 1} for i, t in enumerate(src.topic_keywords(live, top_n=25))]
        if category:
            cl = category.lower()
            rows = [r for r in rows if cl in r["topic"].lower()] or rows
    result = {"platform": platform, "category": category, "count": len(rows),
              "trending": rows, "note": "velocity = engagement per hour since posting",
              "billing": _billing(dec)}
    result["provenance"] = await _attest(result, f"trending_topics {platform}")
    return result


# ── topic_sentiment ($0.01) ───────────────────────────────────────────────────
async def do_topic_sentiment(topic, *, agent_key, payment_tx=None, api_key=None):
    if not topic:
        return {"error": "bad_request", "detail": "topic is required"}
    price = payment_gate._price_for("topic_sentiment")
    dec = await payment_gate.precheck("topic_sentiment", {"topic": topic}, price, agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        return dec["body"]

    # Pull discussion from each platform live (deterministic sentiment per item).
    reddit = await src.reddit_search(topic, limit=25)
    hn = await src.hn_search(topic, limit=25)
    cached = await supa.content_for_topic(topic, limit=50)
    all_items = reddit + hn + cached

    by_platform = {}
    for it in all_items:
        plat = it.get("platform") or "other"
        by_platform.setdefault(plat, []).append(it)

    platform_sentiment = {}
    for plat, items in by_platform.items():
        scores = [it.get("sentiment") for it in items if it.get("sentiment") is not None]
        avg = round(sum(scores) / len(scores), 4) if scores else 0.0
        platform_sentiment[plat] = {"sentiment_score": avg, "label": src.sentiment_label(avg),
                                    "sample_size": len(items)}

    overall_scores = [it.get("sentiment") for it in all_items if it.get("sentiment") is not None]
    overall = round(sum(overall_scores) / len(overall_scores), 4) if overall_scores else 0.0

    # Volume trend: recent (cached snapshots) vs live discovered.
    volume_trend = "rising" if len(reddit) + len(hn) > len(cached) else (
        "steady" if cached else "new")

    threads = sorted(all_items, key=lambda x: float(x.get("velocity") or 0), reverse=True)[:8]
    key_threads = [{"platform": t.get("platform"), "title": t.get("title"),
                    "url": t.get("url"), "community": t.get("community"),
                    "score": t.get("score"), "comments": t.get("comments"),
                    "sentiment": t.get("sentiment")} for t in threads]

    result = {
        "topic": topic,
        "overall_sentiment": {"score": overall, "label": src.sentiment_label(overall)},
        "by_platform": platform_sentiment,
        "volume_trend": volume_trend,
        "key_discussion_threads": key_threads,
        "sample_size": len(all_items),
        "note": "sentiment is a deterministic lexicon heuristic (no LLM)",
        "billing": _billing(dec),
    }
    result["provenance"] = await _attest(result, f"topic_sentiment {topic}")
    return result


# ── viral_content ($0.01) ─────────────────────────────────────────────────────
async def do_viral_content(hours_back, min_score, *, agent_key, payment_tx=None, api_key=None):
    params = {k: v for k, v in {"hours_back": hours_back, "min_score": min_score}.items()
              if v not in (None, "")}
    price = payment_gate._price_for("viral_content")
    dec = await payment_gate.precheck("viral_content", params, price, agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        return dec["body"]

    since = None
    if hours_back:
        since = int(_now_utc() - int(hours_back) * 3600)
    rows = await supa.viral_content(since_utc=since, min_score=min_score, limit=30)
    if not rows:
        live = await src.collect_trending()
        if min_score:
            live = [r for r in live if (r.get("score") or 0) >= int(min_score)]
        rows = sorted(live, key=lambda x: float(x.get("velocity") or 0), reverse=True)[:30]

    result = {"hours_back": hours_back, "min_score": min_score, "count": len(rows),
              "viral": rows, "note": "ranked by velocity (engagement per hour)",
              "billing": _billing(dec)}
    result["provenance"] = await _attest(result, "viral_content")
    return result


# ── community_pulse ($0.01) ───────────────────────────────────────────────────
async def do_community_pulse(subreddit, hn_topic, *, agent_key, payment_tx=None, api_key=None):
    params = {k: v for k, v in {"subreddit": subreddit, "hn_topic": hn_topic}.items() if v}
    price = payment_gate._price_for("community_pulse")
    dec = await payment_gate.precheck("community_pulse", params, price, agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        return dec["body"]

    items = []
    if subreddit:
        items += await src.reddit_hot(subreddit, limit=25)
    if hn_topic:
        items += await src.hn_search(hn_topic, limit=25)
    if not subreddit and not hn_topic:
        items += await src.hn_top(limit=25)

    scores = [it.get("sentiment") for it in items if it.get("sentiment") is not None]
    avg = round(sum(scores) / len(scores), 4) if scores else 0.0
    total_engagement = sum((it.get("score") or 0) + (it.get("comments") or 0) for it in items)
    activity = "high" if total_engagement > 5000 else ("moderate" if total_engagement > 500 else "low")
    hot = sorted(items, key=lambda x: float(x.get("velocity") or 0), reverse=True)[:10]
    hot_topics = [{"title": h.get("title"), "url": h.get("url"), "score": h.get("score"),
                   "comments": h.get("comments"), "velocity": h.get("velocity"),
                   "sentiment": h.get("sentiment")} for h in hot]

    result = {
        "subreddit": subreddit, "hn_topic": hn_topic,
        "hot_topics": hot_topics,
        "sentiment": {"score": avg, "label": src.sentiment_label(avg)},
        "activity_level": activity,
        "total_engagement": total_engagement,
        "sample_size": len(items),
        "billing": _billing(dec),
    }
    result["provenance"] = await _attest(result, "community_pulse")
    return result


# ── brand_mentions ($0.02) ────────────────────────────────────────────────────
async def do_brand_mentions(brand, days_back, *, agent_key, payment_tx=None, api_key=None):
    if not brand:
        return {"error": "bad_request", "detail": "brand is required"}
    params = {k: v for k, v in {"brand": brand, "days_back": days_back}.items() if v not in (None, "")}
    price = payment_gate._price_for("brand_mentions")
    dec = await payment_gate.precheck("brand_mentions", params, price, agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        return dec["body"]

    tf = "week"
    if days_back:
        d = int(days_back)
        tf = "day" if d <= 1 else ("week" if d <= 7 else ("month" if d <= 31 else "year"))
    reddit = await src.reddit_search(brand, limit=30, sort="new", time_filter=tf)
    hn = await src.hn_search(brand, limit=30)
    cached = await supa.content_for_topic(brand, limit=40)
    mentions = reddit + hn + cached

    scores = [m.get("sentiment") for m in mentions if m.get("sentiment") is not None]
    avg = round(sum(scores) / len(scores), 4) if scores else 0.0
    pos = sum(1 for s in scores if s > 0.15)
    neg = sum(1 for s in scores if s < -0.15)
    neu = len(scores) - pos - neg

    items = sorted(mentions, key=lambda x: float(x.get("velocity") or 0), reverse=True)[:25]
    mention_rows = [{"platform": m.get("platform"), "title": m.get("title"),
                     "url": m.get("url"), "community": m.get("community"),
                     "score": m.get("score"), "comments": m.get("comments"),
                     "sentiment": m.get("sentiment"),
                     "label": src.sentiment_label(m.get("sentiment") or 0.0)} for m in items]

    result = {
        "brand": brand, "days_back": days_back,
        "mention_count": len(mentions),
        "sentiment": {"score": avg, "label": src.sentiment_label(avg),
                      "positive": pos, "neutral": neu, "negative": neg},
        "mentions": mention_rows,
        "note": "mentions across Reddit + Hacker News with deterministic sentiment + context",
        "billing": _billing(dec),
    }
    result["provenance"] = await _attest(result, f"brand_mentions {brand}")
    return result


# ── daily_brief (premium, curated) ────────────────────────────────────────────
async def do_daily_brief(date, *, agent_key, payment_tx=None, api_key=None):
    day = (date or datetime.now(timezone.utc).strftime("%Y-%m-%d")).strip()
    price = payment_gate._price_for("daily_brief", config.PRICE_DAILY_BRIEF)
    dec = await payment_gate.precheck("daily_brief", {"date": day}, price,
                                      agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        return dec["body"]
    brief = await daily_curator.get_brief(day)
    if not brief:
        return {"error": "not_available",
                "detail": f"No brief for {day} (not yet generated, or expired at midnight UTC). "
                          f"Briefs are curated daily at {config.BRIEF_HOUR_UTC:02d}:00 UTC.",
                "billing": _billing(dec)}
    await daily_curator.bump_purchase(day)
    return {**brief, "billing": _billing(dec)}


def mint_info():
    return {
        "network": "FoundryNet Data Network",
        "message": "Attest your agent's social-trends analysis with MINT Protocol for verifiable proof.",
        "mint_protocol": {"mcp_endpoint": config.MINT_MCP_URL, "info_url": config.MINT_INFO_URL,
                          "tools": ["mint_register", "mint_attest", "mint_verify",
                                    "mint_rate", "mint_recommend", "mint_discover"]},
        "see_also": config.SISTER_SERVERS,
    }
